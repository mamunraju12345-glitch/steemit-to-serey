import os
import re
import json
import time
import html
import requests

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# CONFIG
# ============================================================

SITE_URL = "https://bengali.serey.io"
NEW_POST_URL = f"{SITE_URL}/blog/post/new"

STEEM_USERNAME = os.getenv("STEEM_USERNAME", "").strip()
SEREY_USERNAME = os.getenv("SEREY_USERNAME", "").strip()
SEREY_PASSWORD = os.getenv("SEREY_PASSWORD", "").strip()

SYNC_FILE = "synced_posts.json"

# প্রতি GitHub Actions run-এ ১টি post
POSTS_PER_RUN = 1

# Steem-এর পুরোনো 1000 post আগে শেষ করবে
OLDEST_POST_LIMIT = 1000


# ============================================================
# PERMANENTLY SKIPPED POSTS
# ============================================================

PERMANENTLY_SKIPPED = {
    "mamun123456/-4ac8aa756c94d",
    "mamun123456/-709cad84fe936",
    "mamun123456/-c03668de5eadb",
    "mamun123456/7b7def53-7953-11e8-ac3d-0242ac110003",
    "mamun123456/being-a-good-man-and-being-a-bad-person-is-easy-method-3a94ff5da598",
    "mamun123456/c4lw147p",
    "mamun123456/cf30d320-7a61-11e8-827c-49f76fdbeab3",
    "mamun123456/coconut-water-has-many-advantages",
    "mamun123456/my-little-brother-photography-and-some-story-55445d86075ec",
    "mamun123456/vh2aqw72",
    "mamun123456/what-should-we-do-if-jaundice-96b00cbcf18c8",
}


# ============================================================
# HELPERS
# ============================================================

def normalize_post_id(author, permlink=None):
    if permlink is None:
        value = str(author).strip()

        value = re.sub(
            r"^https?://(?:www\.)?steemit\.com/",
            "",
            value,
            flags=re.I,
        )

        value = value.split("?")[0]
        value = value.split("#")[0]
        value = value.strip("/")

        if value.startswith("@"):
            value = value[1:]

        return value

    author = str(author).strip().lstrip("@")
    permlink = str(permlink).strip().strip("/")

    return f"{author}/{permlink}"


def clean_body(body):
    body = html.unescape(str(body or ""))

    body = re.sub(
        r"<!--.*?-->",
        "",
        body,
        flags=re.S,
    )

    body = re.sub(
        r"^\s*---.*?---\s*",
        "",
        body,
        flags=re.S,
    )

    body = re.sub(
        r"\n{4,}",
        "\n\n\n",
        body,
    )

    return body.strip()


def extract_image(body):
    if not body:
        return None

    patterns = [
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        r'https?://cdn\.steemitimages\.com/[^\s"\')<>]+',
        r'https?://steemitimages\.com/[^\s"\')<>]+',
        r'https?://img\.esteem\.ws/[^\s"\')<>]+',
        r'https?://[^\s"\')<>]+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s"\')<>]*)?',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            body,
            flags=re.I,
        )

        if match:
            return match.group(1) if match.lastindex else match.group(0)

    return None


# ============================================================
# SYNC FILE
# ============================================================

def load_synced_posts():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if not isinstance(data, list):
            return set()

        return {
            normalize_post_id(item)
            for item in data
            if item
        }

    except Exception as e:
        print(
            f"⚠️ Could not read {SYNC_FILE}: {e}"
        )
        return set()


def save_synced_posts(posts):
    with open(
        SYNC_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            sorted(posts),
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# STEEM RPC
# ============================================================

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://steemd.privex.io",
]


def steem_rpc(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    last_error = None

    for node in STEEM_NODES:
        try:
            response = requests.post(
                node,
                json=payload,
                timeout=30,
                headers={
                    "User-Agent": "Steem-Serey-Sync/1.0"
                },
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise RuntimeError(
                    data["error"]
                )

            return data.get("result")

        except Exception as e:
            last_error = e
            print(
                f"⚠️ RPC failed: {node} -> {e}"
            )

    raise RuntimeError(
        f"All Steem RPC nodes failed: {last_error}"
    )


def get_all_steem_posts():
    print("=" * 40)
    print("GETTING STEEM POSTS")
    print("=" * 40)

    all_posts = []
    seen_ids = set()

    start_author = STEEM_USERNAME
    start_permlink = ""

    page = 0

    while True:
        page += 1

        try:
            result = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                [
                    {
                        "tag": STEEM_USERNAME,
                        "limit": 100,
                        "start_author": start_author,
                        "start_permlink": start_permlink,
                    }
                ],
            )

        except Exception as e:
            print(
                f"❌ Steem page {page} failed: {e}"
            )
            break

        if not result:
            break

        print(
            f"Steem page {page}: {len(result)} posts"
        )

        for post in result:

            author = post.get(
                "author",
                "",
            )

            permlink = post.get(
                "permlink",
                "",
            )

            if not author or not permlink:
                continue

            if author.lower() != STEEM_USERNAME.lower():
                continue

            # Parent post only
            if post.get("parent_author"):
                continue

            post_id = normalize_post_id(
                author,
                permlink,
            )

            if post_id in seen_ids:
                continue

            seen_ids.add(post_id)
            all_posts.append(post)

        if len(result) < 100:
            break

        last = result[-1]

        new_author = last.get(
            "author",
            "",
        )

        new_permlink = last.get(
            "permlink",
            "",
        )

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(all_posts) >= 10000:
            break

    # Steem returns newest → oldest
    # We need oldest → newest
    all_posts.reverse()

    print(
        f"Total posts: {len(all_posts)}"
    )

    return all_posts


# ============================================================
# IMAGE
# ============================================================

def download_image(image_url):
    if not image_url:
        return None

    print(
        f"Downloading image: {image_url}"
    )

    urls = [image_url]

    # CDN fallback
    match = re.search(
        r"/([A-Za-z0-9_-]{8,})\.(jpg|jpeg|png|gif|webp)$",
        image_url,
        flags=re.I,
    )

    if match:
        image_name = match.group(1)
        extension = match.group(2)

        urls.extend([
            f"https://steemitimages.com/{image_name}.{extension}",
            f"https://steemitimages.com/0x0/{image_name}.{extension}",
        ])

    for url in urls:
        try:
            print(
                f"Trying image: {url}"
            )

            response = requests.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 "
                        "Chrome/120 Safari/537.36"
                    )
                },
            )

            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                ).lower()
            )

            content = response.content

            if not content:
                continue

            is_image = (
                content_type.startswith("image/")
                or content.startswith(b"\xff\xd8\xff")
                or content.startswith(b"\x89PNG")
                or content.startswith(b"GIF8")
                or content.startswith(b"RIFF")
            )

            if not is_image:
                print(
                    f"Not an image: {content_type}"
                )
                continue

            extension = "jpg"

            if "png" in content_type:
                extension = "png"
            elif "gif" in content_type:
                extension = "gif"
            elif "webp" in content_type:
                extension = "webp"

            filename = (
                f"thumbnail.{extension}"
            )

            with open(
                filename,
                "wb",
            ) as f:
                f.write(content)

            print(
                "✓ Image downloaded"
            )

            return filename

        except Exception as e:
            print(
                f"Image attempt failed: {e}"
            )

    print(
        "⚠️ Image unavailable. Continuing without image."
    )

    return None


# ============================================================
# REAL IMAGE CROP MODAL ONLY
# ============================================================

def real_crop_modal(page):
    """
    IMPORTANT:
    শুধু .antd-img-crop-modal-কে crop modal হিসেবে ধরা হবে।

    Generic .ant-modal-wrap ব্যবহার করা হবে না,
    কারণ Serey-এর Publish/Category modal-ও ant-modal-wrap।
    """

    try:
        modal = page.locator(
            ".antd-img-crop-modal:visible"
        )

        if modal.count() > 0:
            return modal.last

    except Exception:
        pass

    return None


def close_real_crop_modal(page):
    """
    Thumbnail crop modal থাকলে সেটি confirm করবে।
    """

    modal = real_crop_modal(page)

    if not modal:
        return True

    print(
        "✓ REAL IMAGE CROP MODAL DETECTED."
    )

    # Crop modal-এর সাধারণ confirmation buttons
    patterns = [
        r"^ok$",
        r"^confirm$",
        r"^save$",
        r"^done$",
        r"^crop$",
        r"确定",
        r"确认",
        r"保存",
        r"完成",
    ]

    buttons = modal.locator(
        "button"
    )

    for i in range(
        buttons.count()
    ):
        try:
            button = buttons.nth(i)

            if not button.is_visible():
                continue

            text = (
                button.inner_text(
                    timeout=1000
                ).strip()
            )

            for pattern in patterns:
                if re.search(
                    pattern,
                    text,
                    flags=re.I,
                ):
                    print(
                        f"✓ Crop confirm: {text}"
                    )

                    button.click(
                        timeout=10000
                    )

                    page.wait_for_timeout(
                        1500
                    )

                    if not real_crop_modal(page):
                        print(
                            "✓ Image crop modal closed."
                        )
                        return True

        except Exception:
            continue

    # Try last non-cancel button
    for i in range(
        buttons.count() - 1,
        -1,
        -1,
    ):
        try:
            button = buttons.nth(i)

            if not button.is_visible():
                continue

            text = (
                button.inner_text(
                    timeout=1000
                ).strip().lower()
            )

            if text in {
                "cancel",
                "close",
            }:
                continue

            try:
                button.click(
                    timeout=5000
                )

                page.wait_for_timeout(
                    1000
                )

                if not real_crop_modal(page):
                    print(
                        "✓ Crop modal closed."
                    )
                    return True

            except Exception:
                pass

        except Exception:
            continue

    print(
        "⚠️ Real crop modal could not be closed."
    )

    return False


# ============================================================
# FORM
# ============================================================

def fill_title(page, title):
    selectors = [
        "input[placeholder*='Title' i]",
        "textarea[placeholder*='Title' i]",
        "input[name='title']",
        "textarea[name='title']",
    ]

    for selector in selectors:
        try:
            elements = page.locator(
                selector
            )

            for i in range(
                elements.count()
            ):
                element = elements.nth(i)

                if not element.is_visible():
                    continue

                element.fill(title)

                print(
                    "✓ Title filled"
                )

                return True

        except Exception:
            pass

    # fallback
    try:
        inputs = page.locator(
            "input, textarea"
        )

        for i in range(
            inputs.count()
        ):
            element = inputs.nth(i)

            if not element.is_visible():
                continue

            element.fill(title)

            print(
                "✓ Title filled"
            )

            return True

    except Exception:
        pass

    print(
        "❌ Could not fill title"
    )

    return False


def fill_body(page, body):
    selectors = [
        "textarea[placeholder*='Content' i]",
        "textarea[placeholder*='content' i]",
        "textarea[name='body']",
        "textarea",
        ".ProseMirror",
        "[contenteditable='true']",
    ]

    for selector in selectors:
        try:
            elements = page.locator(
                selector
            )

            for i in range(
                elements.count()
            ):
                element = elements.nth(i)

                if not element.is_visible():
                    continue

                tag = element.evaluate(
                    "(el) => el.tagName"
                )

                if tag == "TEXTAREA":
                    element.fill(body)

                else:
                    element.click()

                    page.keyboard.press(
                        "Control+A"
                    )

                    page.keyboard.insert_text(
                        body
                    )

                print(
                    "✓ Body filled"
                )

                return True

        except Exception:
            pass

    print(
        "❌ Could not fill body"
    )

    return False


def upload_thumbnail(page, image_path):
    if not image_path:
        print(
            "No thumbnail available."
        )
        return True

    try:
        inputs = page.locator(
            "input[type='file']"
        )

        if inputs.count() == 0:
            print(
                "⚠️ File input not found."
            )
            return True

        for i in range(
            inputs.count()
        ):
            inp = inputs.nth(i)

            try:
                inp.set_input_files(
                    image_path
                )

                print(
                    "✓ Thumbnail uploaded."
                )

                page.wait_for_timeout(
                    2000
                )

                # ONLY real crop modal
                if not close_real_crop_modal(
                    page
                ):
                    print(
                        "⚠️ Crop modal could not be confirmed."
                    )

                return True

            except Exception as e:
                print(
                    f"File upload failed: {e}"
                )

    except Exception as e:
        print(
            f"Thumbnail upload error: {e}"
        )

    print(
        "⚠️ Continuing without thumbnail."
    )

    return True


# ============================================================
# PUBLISH BUTTON
# ============================================================

def get_visible_publish_buttons(page):
    result = []

    elements = page.locator(
        "button, input[type='submit'], input[type='button'], a"
    )

    try:
        count = elements.count()
    except Exception:
        return result

    for i in range(count):
        try:
            element = elements.nth(i)

            if not element.is_visible():
                continue

            tag = element.evaluate(
                "(el) => el.tagName"
            )

            text = ""

            if tag != "INPUT":
                try:
                    text = element.inner_text(
                        timeout=1000
                    ).strip()
                except Exception:
                    pass

            value = (
                element.get_attribute(
                    "value"
                )
                or ""
            )

            aria = (
                element.get_attribute(
                    "aria-label"
                )
                or ""
            )

            combined = (
                f"{text} {value} {aria}"
            ).strip().lower()

            if "publish" in combined:
                result.append(element)

        except Exception:
            continue

    return result


def click_first_publish(page):
    print(
        "Searching for FIRST Publish..."
    )

    buttons = get_visible_publish_buttons(
        page
    )

    print(
        f"Visible Publish buttons: {len(buttons)}"
    )

    if not buttons:
        return False

    button = buttons[-1]

    try:
        button.scroll_into_view_if_needed(
            timeout=5000
        )

        page.wait_for_timeout(
            500
        )

        button.click(
            timeout=15000
        )

        print(
            "✓ FIRST Publish CLICKED"
        )

        return True

    except Exception as e:
        print(
            f"Normal click failed: {e}"
        )

        try:
            button.click(
                timeout=10000,
                force=True,
            )

            print(
                "✓ FIRST Publish FORCE CLICKED"
            )

            return True

        except Exception as e2:
            print(
                f"❌ First Publish failed: {e2}"
            )
            return False


# ============================================================
# SEREY CONFIRMATION / CATEGORY MODAL
# ============================================================

def click_publish_in_serey_modal(page):
    """
    FIRST Publish-এর পরে Serey যে modal খুলে,
    সেখানে Publish button থাকলে সেটি চাপবে।

    IMPORTANT:
    এখানে generic ant-modal-wrap ইচ্ছাকৃতভাবে ব্যবহার করছি,
    কারণ এবার আমরা এটাকে crop modal হিসেবে ধরছি না।
    """

    print(
        "Checking Serey confirmation modal..."
    )

    for attempt in range(12):

        page.wait_for_timeout(
            1000
        )

        # Real image crop modal হলে আগে handle
        crop = real_crop_modal(page)

        if crop:
            print(
                "Image crop modal still open."
            )

            if not close_real_crop_modal(
                page
            ):
                return False

            continue

        # Generic visible Ant modal
        modals = page.locator(
            ".ant-modal-wrap:visible"
        )

        if modals.count() == 0:
            # Maybe modal is not using ant class
            continue

        # Use last visible modal
        modal = modals.last

        try:
            text = (
                modal.inner_text(
                    timeout=2000
                ).strip()
            )

            print(
                "Serey modal detected:"
            )

            print(
                text[:500]
            )

        except Exception:
            pass

        # Find Publish buttons INSIDE MODAL
        buttons = modal.locator(
            "button, input[type='submit'], "
            "input[type='button'], a"
        )

        candidates = []

        for i in range(
            buttons.count()
        ):
            try:
                button = buttons.nth(i)

                if not button.is_visible():
                    continue

                tag = button.evaluate(
                    "(el) => el.tagName"
                )

                text = ""

                if tag != "INPUT":
                    try:
                        text = button.inner_text(
                            timeout=1000
                        ).strip()
                    except Exception:
                        pass

                value = (
                    button.get_attribute(
                        "value"
                    )
                    or ""
                )

                aria = (
                    button.get_attribute(
                        "aria-label"
                    )
                    or ""
                )

                combined = (
                    f"{text} {value} {aria}"
                ).strip()

                if re.search(
                    r"\bpublish\b",
                    combined,
                    flags=re.I,
                ):
                    candidates.append(
                        button
                    )

            except Exception:
                continue

        if candidates:

            print(
                f"✓ Publish button found inside Serey modal: "
                f"{len(candidates)}"
            )

            # Last Publish button is normally the confirmation
            button = candidates[-1]

            try:
                button.scroll_into_view_if_needed(
                    timeout=5000
                )

                page.wait_for_timeout(
                    500
                )

                button.click(
                    timeout=15000
                )

                print(
                    "✓ SEREY MODAL PUBLISH CLICKED"
                )

                page.wait_for_timeout(
                    3000
                )

                return True

            except Exception as e:
                print(
                    f"Normal modal Publish failed: {e}"
                )

                try:
                    button.click(
                        timeout=10000,
                        force=True,
                    )

                    print(
                        "✓ SEREY MODAL PUBLISH FORCE CLICKED"
                    )

                    page.wait_for_timeout(
                        3000
                    )

                    return True

                except Exception as e2:
                    print(
                        f"❌ Modal Publish failed: {e2}"
                    )

                    return False

        # If modal exists but no Publish,
        # don't randomly click "Back".
        print(
            "Modal found, but Publish button not found yet."
        )

    print(
        "⚠️ Serey confirmation modal not handled."
    )

    return False


# ============================================================
# CATEGORY
# ============================================================

def handle_category(page, category):
    print(
        f"Steemit category: {category}"
    )

    if not category:
        return True

    # We DO NOT randomly interact with generic modals here.
    # Serey itself may suggest category automatically.

    selectors = [
        "input[placeholder*='Category' i]",
        "input[placeholder*='category' i]",
        "[role='combobox']",
    ]

    for selector in selectors:
        try:
            elements = page.locator(
                selector
            )

            for i in range(
                elements.count()
            ):
                element = elements.nth(i)

                if not element.is_visible():
                    continue

                try:
                    element.click()

                    element.fill(
                        category
                    )

                    page.wait_for_timeout(
                        800
                    )

                    options = page.locator(
                        "[role='option'], "
                        ".ant-select-item-option, "
                        ".ant-dropdown-menu-item"
                    )

                    for j in range(
                        options.count()
                    ):
                        option = options.nth(j)

                        if not option.is_visible():
                            continue

                        text = (
                            option.inner_text(
                                timeout=1000
                            ).strip()
                        )

                        if text.lower() == category.lower():
                            option.click()

                            print(
                                "✓ Category handled."
                            )

                            return True

                except Exception:
                    pass

        except Exception:
            pass

    print(
        "No category selector. Continuing."
    )

    return True


# ============================================================
# LOGIN
# ============================================================

def login_serey(page):
    print(
        "Logging into Serey..."
    )

    page.goto(
        NEW_POST_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(
        3000
    )

    password_inputs = page.locator(
        "input[type='password']"
    )

    if password_inputs.count() > 0:

        username_selectors = [
            "input[type='email']",
            "input[name='username']",
            "input[name='email']",
            "input[placeholder*='username' i]",
            "input[placeholder*='email' i]",
        ]

        username_filled = False

        for selector in username_selectors:
            try:
                elements = page.locator(
                    selector
                )

                for i in range(
                    elements.count()
                ):
                    element = elements.nth(i)

                    if not element.is_visible():
                        continue

                    element.fill(
                        SEREY_USERNAME
                    )

                    username_filled = True
                    break

                if username_filled:
                    break

            except Exception:
                pass

        if not username_filled:
            print(
                "❌ Serey username field not found."
            )
            return False

        try:
            password_inputs.first.fill(
                SEREY_PASSWORD
            )

        except Exception:
            print(
                "❌ Serey password field not found."
            )
            return False

        login_buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"login|sign in",
                re.I,
            ),
        )

        if login_buttons.count() > 0:

            try:
                login_buttons.first.click(
                    timeout=15000
                )

            except Exception:
                login_buttons.first.click(
                    timeout=10000,
                    force=True,
                )

        else:

            try:
                page.locator(
                    "button[type='submit'], "
                    "input[type='submit']"
                ).first.click(
                    timeout=10000
                )

            except Exception as e:
                print(
                    f"❌ Login button not found: {e}"
                )
                return False

        page.wait_for_timeout(
            5000
        )

    try:
        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    except Exception:
        pass

    page.wait_for_timeout(
        2500
    )

    if "/login" in page.url.lower():
        print(
            "❌ Login failed."
        )
        return False

    if page.locator(
        "input[type='password']"
    ).count() > 0:
        print(
            "❌ Login not verified."
        )
        return False

    print(
        "✓ SEREY LOGIN VERIFIED!"
    )

    return True


# ============================================================
# VERIFY
# ============================================================

def verify_publication(page):
    print(
        "VERIFYING PUBLISHED POST..."
    )

    for _ in range(20):

        page.wait_for_timeout(
            2000
        )

        current_url = page.url

        print(
            f"Current URL: {current_url}"
        )

        # EXACT SUCCESS PATTERN
        if re.search(
            r"/authors/[^/]+/[^/?#]+",
            current_url,
            flags=re.I,
        ):
            print(
                "✓ POST URL FOUND!"
            )
            return True

        # Search page for author links
        try:
            links = page.locator(
                "a[href*='/authors/']"
            )

            for i in range(
                links.count()
            ):
                link = links.nth(i)

                if not link.is_visible():
                    continue

                href = (
                    link.get_attribute(
                        "href"
                    )
                    or ""
                )

                if re.search(
                    r"/authors/[^/]+/[^/?#]+",
                    href,
                    flags=re.I,
                ):
                    print(
                        f"✓ POST LINK FOUND: {href}"
                    )
                    return True

        except Exception:
            pass

    print(
        "❌ Publication could not be verified."
    )

    return False


# ============================================================
# DEBUG
# ============================================================

def save_debug(page):
    try:
        page.screenshot(
            path="serey_error.png",
            full_page=True,
        )

        print(
            "Debug screenshot saved: serey_error.png"
        )

    except Exception as e:
        print(
            f"Screenshot failed: {e}"
        )

    try:
        with open(
            "serey_error.html",
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                page.content()
            )

        print(
            "Debug HTML saved: serey_error.html"
        )

    except Exception as e:
        print(
            f"HTML save failed: {e}"
        )


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish_post(page, post):

    author = post.get(
        "author",
        "",
    )

    permlink = post.get(
        "permlink",
        "",
    )

    title = str(
        post.get(
            "title",
            "",
        )
        or ""
    ).strip()

    body = clean_body(
        post.get(
            "body",
            "",
        )
    )

    category = str(
        post.get(
            "category",
            "",
        )
        or ""
    ).strip()

    post_id = normalize_post_id(
        author,
        permlink,
    )

    print("=" * 40)
    print(
        f"Publishing: {title}"
    )
    print(
        f"Post ID: {post_id}"
    )
    print("=" * 40)

    image_url = extract_image(
        body
    )

    image_path = None

    if image_url:
        image_path = download_image(
            image_url
        )
    else:
        print(
            "No thumbnail available."
        )

    try:

        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(
            2500
        )

        print(
            f"New post URL: {page.url}"
        )

        if not fill_title(
            page,
            title,
        ):
            return False

        if not fill_body(
            page,
            body,
        ):
            return False

        if image_path:
            upload_thumbnail(
                page,
                image_path,
            )

        # IMPORTANT:
        # Only real image crop modal is handled here.
        if real_crop_modal(page):

            if not close_real_crop_modal(
                page
            ):
                print(
                    "❌ Image crop modal remains open."
                )

                save_debug(page)
                return False

        # ====================================================
        # FIRST PUBLISH
        # ====================================================

        if not click_first_publish(
            page
        ):
            print(
                "❌ FIRST Publish button not found."
            )

            save_debug(page)
            return False

        page.wait_for_timeout(
            1500
        )

        print(
            f"URL after first Publish: {page.url}"
        )

        # ====================================================
        # CATEGORY
        # ====================================================

        handle_category(
            page,
            category,
        )

        # ====================================================
        # SEREY CONFIRMATION MODAL
        # ====================================================

        print(
            "Searching for Serey Publish confirmation..."
        )

        if not click_publish_in_serey_modal(
            page
        ):

            # It is possible Serey did not open a modal.
            # Check normal Publish button as fallback.
            print(
                "No confirmation modal Publish completed."
            )

            buttons = get_visible_publish_buttons(
                page
            )

            if buttons:

                print(
                    f"Fallback Publish buttons: {len(buttons)}"
                )

                try:
                    buttons[-1].click(
                        timeout=10000
                    )

                    print(
                        "✓ FINAL Publish CLICKED"
                    )

                except Exception as e:
                    print(
                        f"❌ Final Publish failed: {e}"
                    )

                    save_debug(page)
                    return False

            else:
                print(
                    "❌ FINAL Publish button not found."
                )

                save_debug(page)
                return False

        # ====================================================
        # VERIFY REAL SEREY URL
        # ====================================================

        success = verify_publication(
            page
        )

        if success:
            return True

        save_debug(page)

        return False

    except Exception as e:

        print(
            f"❌ Publish exception: {e}"
        )

        save_debug(page)

        return False

    finally:

        if image_path:
            try:
                os.remove(
                    image_path
                )
            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 40)
    print(
        "STEEMIT → BENGALI SEREY AUTO SYNC"
    )
    print("=" * 40)

    # --------------------------------------------------------
    # ENVIRONMENT
    # --------------------------------------------------------

    if not STEEM_USERNAME:
        print(
            "❌ STEEM_USERNAME is missing."
        )
        return

    if not SEREY_USERNAME:
        print(
            "❌ SEREY_USERNAME is missing."
        )
        return

    if not SEREY_PASSWORD:
        print(
            "❌ SEREY_PASSWORD is missing."
        )
        return

    # --------------------------------------------------------
    # SYNC FILE
    # --------------------------------------------------------

    synced = load_synced_posts()

    print(
        f"Previously synced: {len(synced)}"
    )

    # --------------------------------------------------------
    # STEEM POSTS
    # --------------------------------------------------------

    posts = get_all_steem_posts()

    if not posts:
        print(
            "❌ No Steem posts found."
        )
        return

    # --------------------------------------------------------
    # OLDEST 1000
    # --------------------------------------------------------

    selected_posts = posts[
        :OLDEST_POST_LIMIT
    ]

    print(
        f"Selected oldest posts: "
        f"{len(selected_posts)}"
    )

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    permanent_count = 0
    synced_count = 0

    unsynced = []

    for post in selected_posts:

        author = post.get(
            "author",
            "",
        )

        permlink = post.get(
            "permlink",
            "",
        )

        if not author or not permlink:
            continue

        post_id = normalize_post_id(
            author,
            permlink,
        )

        # Permanent skip
        if post_id in PERMANENTLY_SKIPPED:
            permanent_count += 1
            continue

        # Already successfully published
        if post_id in synced:
            synced_count += 1
            continue

        unsynced.append(
            post
        )

    print(
        f"Permanent skipped posts found: "
        f"{permanent_count}"
    )

    print(
        f"Already synced posts found: "
        f"{synced_count}"
    )

    print(
        f"Unsynced posts in oldest "
        f"{OLDEST_POST_LIMIT}: "
        f"{len(unsynced)}"
    )

    if not unsynced:

        print(
            "✓ Oldest 1000 posts are completed."
        )

        print(
            "No newer posts will be selected automatically."
        )

        return

    posts_to_publish = unsynced[
        :POSTS_PER_RUN
    ]

    print(
        f"Publishing this run: "
        f"{len(posts_to_publish)}"
    )

    # --------------------------------------------------------
    # BROWSER
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-US",
        )

        page = context.new_page()

        try:

            # LOGIN
            if not login_serey(page):
                print(
                    "❌ SEREY LOGIN FAILED."
                )
                return

            # PUBLISH
            for post in posts_to_publish:

                post_id = normalize_post_id(
                    post.get(
                        "author",
                        "",
                    ),
                    post.get(
                        "permlink",
                        "",
                    ),
                )

                success = publish_post(
                    page,
                    post,
                )

                if success:

                    # ONLY real Serey success
                    synced.add(
                        post_id
                    )

                    save_synced_posts(
                        synced
                    )

                    print(
                        f"✓ SAVED AS SYNCED: "
                        f"{post_id}"
                    )

                else:

                    print(
                        f"❌ FAILED: {post_id}"
                    )

                    print(
                        "⚠️ This post was NOT "
                        "added to synced_posts.json."
                    )

        finally:

            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass

    print("=" * 40)
    print(
        "SYNC COMPLETED"
    )
    print("=" * 40)


if __name__ == "__main__":
    main()
