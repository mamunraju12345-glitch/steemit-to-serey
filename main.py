import os
import re
import json
import time
import html
import requests
from urllib.parse import urljoin

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

# প্রতি GitHub Actions run-এ কতটি post publish করবে
POSTS_PER_RUN = 1

# পুরোনো post থেকে সর্বোচ্চ কতটি post queue হিসেবে ব্যবহার করবে
OLDEST_POST_LIMIT = 1000

HEADLESS = True


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
# BASIC HELPERS
# ============================================================

def normalize_post_id(author, permlink=None):
    """
    সব ধরনের Steem post reference-কে:
        author/permlink
    format-এ আনে।
    """

    if permlink is None:
        value = str(author).strip()

        value = re.sub(
            r"^https?://(?:www\.)?steemit\.com/",
            "",
            value,
            flags=re.I,
        )

        value = value.split("?")[0].split("#")[0]
        value = value.strip("/")

        if value.startswith("@"):
            value = value[1:]

        return value

    author = str(author).strip().lstrip("@")
    permlink = str(permlink).strip().strip("/")

    return f"{author}/{permlink}"


def safe_text(value):
    if value is None:
        return ""

    value = html.unescape(str(value))
    return value.strip()


def clean_body(body):
    """
    Steem body থেকে কিছু problematic HTML/metadata পরিষ্কার করে।
    """

    body = safe_text(body)

    # HTML comments
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)

    # Steem front matter style metadata
    body = re.sub(
        r"^\s*---.*?---\s*",
        "",
        body,
        flags=re.S,
    )

    # Very large repeated whitespace
    body = re.sub(r"\n{4,}", "\n\n\n", body)

    return body.strip()


def extract_image(body):
    """
    Body-এর প্রথম usable image URL বের করে।
    """

    if not body:
        return None

    patterns = [
        r'https?://[^\s"\')<>]+?\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s"\')<>]*)?',
        r'https?://cdn\.steemitimages\.com/[^\s"\')<>]+',
        r'https?://steemitimages\.com/[^\s"\')<>]+',
        r'https?://img\.esteem\.ws/[^\s"\')<>]+',
    ]

    for pattern in patterns:
        match = re.search(pattern, body, flags=re.I)

        if match:
            url = match.group(0).rstrip(".,);]")

            return url

    # Markdown image
    match = re.search(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        body,
        flags=re.I,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# SYNC FILE
# ============================================================

def load_synced_posts():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return set()

        result = set()

        for item in data:
            normalized = normalize_post_id(item)

            if normalized:
                result.add(normalized)

        return result

    except Exception as e:
        print(f"⚠️ Could not read {SYNC_FILE}: {e}")
        return set()


def save_synced_posts(posts):
    data = sorted(posts)

    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
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
                raise RuntimeError(data["error"])

            return data.get("result")

        except Exception as e:
            last_error = e
            print(f"⚠️ RPC failed: {node} -> {e}")

    raise RuntimeError(
        f"All Steem RPC nodes failed: {last_error}"
    )


def get_all_steem_posts():
    """
    Account-এর published posts সংগ্রহ করে।

    Steem API newest -> oldest দেয়।
    শেষে list reverse করে oldest -> newest করা হবে।
    """

    print("=" * 40)
    print("GETTING STEEM POSTS")
    print("=" * 40)

    all_posts = []
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
            print(f"❌ Steem page {page} failed: {e}")
            break

        if not result:
            break

        print(
            f"Steem page {page}: {len(result)} posts"
        )

        before = len(all_posts)

        for post in result:
            author = post.get("author", "")
            permlink = post.get("permlink", "")

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

            if post_id not in {
                normalize_post_id(p.get("author", ""), p.get("permlink", ""))
                for p in all_posts
            }:
                all_posts.append(post)

        if len(result) < 100:
            break

        last = result[-1]

        new_author = last.get("author", "")
        new_permlink = last.get("permlink", "")

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        # Safety
        if len(all_posts) >= 10000:
            break

        # Prevent infinite loops
        if len(all_posts) == before:
            break

    # Steem returns newest first.
    # Reverse => oldest first.
    all_posts.reverse()

    print(f"Total posts: {len(all_posts)}")

    return all_posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(image_url):
    if not image_url:
        return None

    print(f"Downloading image: {image_url}")

    urls = [image_url]

    # Steemit CDN fallback
    match = re.search(
        r"/([A-Za-z0-9_-]{8,})\.(jpg|jpeg|png|gif|webp)$",
        image_url,
        flags=re.I,
    )

    if match:
        image_name = match.group(1)
        extension = match.group(2)

        urls.extend(
            [
                f"https://steemitimages.com/{image_name}.{extension}",
                f"https://steemitimages.com/0x0/{image_name}.{extension}",
            ]
        )

    for url in urls:
        try:
            print(f"Trying image: {url}")

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
                    ""
                ).lower()
            )

            content = response.content

            if not content:
                continue

            # Check real image signatures too
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

            filename = f"thumbnail.{extension}"

            with open(filename, "wb") as f:
                f.write(content)

            print("✓ Image downloaded")

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
# PLAYWRIGHT HELPERS
# ============================================================

def visible_publish_buttons(page):
    buttons = page.locator(
        "button, input[type='submit'], input[type='button'], a"
    )

    result = []

    try:
        count = buttons.count()
    except Exception:
        return result

    for i in range(count):
        try:
            element = buttons.nth(i)

            if not element.is_visible():
                continue

            text = (
                element.inner_text(
                    timeout=1000
                ).strip()
                if element.evaluate(
                    "(el) => el.tagName !== 'INPUT'"
                )
                else ""
            )

            value = (
                element.get_attribute("value")
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


def close_image_crop_modal(page):
    """
    Thumbnail upload-এর পরে Serey/Ant Design crop modal
    খোলা থাকলে Confirm/OK/Save/Done button চাপবে।
    """

    print("Checking image crop modal...")

    selectors = [
        ".antd-img-crop-modal",
        ".ant-modal-wrap",
    ]

    modal = None

    for selector in selectors:
        try:
            candidate = page.locator(selector).filter(
                has=page.locator(
                    "button"
                )
            )

            count = candidate.count()

            for i in range(count):
                item = candidate.nth(i)

                if item.is_visible():
                    modal = item
                    break

            if modal:
                break

        except Exception:
            pass

    if not modal:
        print("✓ No image crop modal detected.")
        return True

    print("✓ Image crop modal detected.")

    # First try common button text
    button_texts = [
        "OK",
        "Confirm",
        "Save",
        "Done",
        "Crop",
        "确定",
        "确认",
        "保存",
        "完成",
    ]

    for text in button_texts:
        try:
            button = modal.get_by_role(
                "button",
                name=re.compile(
                    rf"^{re.escape(text)}$",
                    re.I,
                ),
            ).last

            if button.count() > 0 and button.is_visible():
                print(
                    f"✓ Crop modal button found: {text}"
                )

                button.click(
                    timeout=5000
                )

                page.wait_for_timeout(1500)

                # Verify modal disappeared
                if not modal.is_visible():
                    print(
                        "✓ Image crop modal closed."
                    )
                    return True

        except Exception:
            pass

    # Try any visible button in modal except Cancel
    try:
        buttons = modal.locator("button")

        count = buttons.count()

        for i in range(count - 1, -1, -1):
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
                "x",
            }:
                continue

            print(
                f"Trying crop modal button: {text}"
            )

            try:
                button.click(timeout=5000)
                page.wait_for_timeout(1500)

                if not modal.is_visible():
                    print(
                        "✓ Image crop modal closed."
                    )
                    return True

            except Exception:
                continue

    except Exception:
        pass

    # Last resort: Escape
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        if not modal.is_visible():
            print(
                "✓ Image crop modal closed with Escape."
            )
            return True

    except Exception:
        pass

    print(
        "⚠️ Crop modal could not be closed."
    )

    return False


def wait_for_no_modal(page):
    """
    Publish-এর আগে blocking modal আছে কিনা check করে।
    """

    for _ in range(10):
        try:
            blocking = page.locator(
                ".ant-modal-wrap:visible, "
                ".antd-img-crop-modal:visible"
            )

            if blocking.count() == 0:
                return True

        except Exception:
            return True

        close_image_crop_modal(page)
        page.wait_for_timeout(500)

    return False


def click_publish(page, label="PUBLISH"):
    print(
        f"Searching for {label}..."
    )

    if not wait_for_no_modal(page):
        print(
            "❌ Blocking modal is still open."
        )
        return False

    buttons = visible_publish_buttons(page)

    print(
        f"Visible Publish buttons: {len(buttons)}"
    )

    if not buttons:
        return False

    # Usually last visible Publish is the correct action
    button = buttons[-1]

    try:
        button.scroll_into_view_if_needed(
            timeout=5000
        )

        page.wait_for_timeout(500)

        button.click(
            timeout=15000
        )

        print(
            f"✓ {label} CLICKED"
        )

        return True

    except Exception as e:
        print(
            f"Normal click failed: {e}"
        )

        # Do NOT force click if a modal is blocking.
        if not wait_for_no_modal(page):
            print(
                "❌ Publish blocked by modal."
            )
            return False

        try:
            button.click(
                timeout=10000,
                force=True,
            )

            print(
                f"✓ {label} FORCE CLICKED"
            )

            return True

        except Exception as e2:
            print(
                f"❌ Force click failed: {e2}"
            )
            return False


def fill_first_input(page, selectors, value):
    for selector in selectors:
        try:
            locator = page.locator(selector)

            if locator.count() == 0:
                continue

            for i in range(locator.count()):
                element = locator.nth(i)

                if not element.is_visible():
                    continue

                try:
                    element.fill(value)
                    return True
                except Exception:
                    pass

        except Exception:
            pass

    return False


def fill_title(page, title):
    selectors = [
        "input[placeholder*='Title' i]",
        "input[placeholder*='title' i]",
        "textarea[placeholder*='Title' i]",
        "input[name='title']",
        "textarea[name='title']",
    ]

    if fill_first_input(
        page,
        selectors,
        title,
    ):
        print("✓ Title filled")
        return True

    # Fallback: visible input
    try:
        inputs = page.locator(
            "input, textarea"
        )

        for i in range(inputs.count()):
            element = inputs.nth(i)

            if not element.is_visible():
                continue

            element.fill(title)

            print("✓ Title filled")
            return True

    except Exception:
        pass

    print("❌ Could not fill title")
    return False


def fill_body(page, body):
    body_selectors = [
        "textarea[placeholder*='Content' i]",
        "textarea[placeholder*='content' i]",
        "textarea[name='body']",
        "textarea",
        "[contenteditable='true']",
        ".ProseMirror",
    ]

    for selector in body_selectors:
        try:
            elements = page.locator(selector)

            for i in range(elements.count()):
                element = elements.nth(i)

                if not element.is_visible():
                    continue

                try:
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

                    print("✓ Body filled")
                    return True

                except Exception:
                    pass

        except Exception:
            pass

    print("❌ Could not fill body")
    return False


def upload_thumbnail(page, image_path):
    if not image_path:
        print(
            "No thumbnail available."
        )
        return True

    try:
        file_inputs = page.locator(
            "input[type='file']"
        )

        count = file_inputs.count()

        if count == 0:
            print(
                "⚠️ File input not found."
            )
            return True

        for i in range(count):
            inp = file_inputs.nth(i)

            try:
                inp.set_input_files(
                    image_path
                )

                print(
                    "✓ Thumbnail uploaded."
                )

                page.wait_for_timeout(
                    1500
                )

                # Very important:
                # close crop modal before Publish
                close_image_crop_modal(page)

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
# CATEGORY
# ============================================================

def handle_category(page, category):
    print(
        f"Steemit category: {category}"
    )

    if not category:
        return True

    # Search common category controls
    selectors = [
        "input[placeholder*='Category' i]",
        "input[placeholder*='category' i]",
        "[role='combobox']",
        "input",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)

            for i in range(elements.count()):
                element = elements.nth(i)

                if not element.is_visible():
                    continue

                placeholder = (
                    element.get_attribute(
                        "placeholder"
                    )
                    or ""
                ).lower()

                aria = (
                    element.get_attribute(
                        "aria-label"
                    )
                    or ""
                ).lower()

                if (
                    "categor" not in placeholder
                    and "categor" not in aria
                    and selector == "input"
                ):
                    continue

                try:
                    element.click()
                    element.fill(category)

                    page.wait_for_timeout(
                        800
                    )

                    # Select dropdown option
                    options = page.locator(
                        "[role='option'], "
                        ".ant-select-item-option, "
                        ".ant-dropdown-menu-item"
                    )

                    for j in range(options.count()):
                        option = options.nth(j)

                        if not option.is_visible():
                            continue

                        text = (
                            option.inner_text(
                                timeout=1000
                            ).strip()
                        )

                        if (
                            text.lower()
                            == category.lower()
                        ):
                            option.click()
                            print(
                                "✓ Category handled."
                            )
                            return True

                    # Sometimes suggested category
                    page.keyboard.press(
                        "Enter"
                    )

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

    page.wait_for_timeout(3000)

    # Check if login fields exist
    password_inputs = page.locator(
        "input[type='password']"
    )

    if password_inputs.count() > 0:
        print(
            "Login form detected."
        )

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
                elements = page.locator(selector)

                for i in range(elements.count()):
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

        # Login button
        login_buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"login|sign in|เข้าสู่ระบบ",
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
            # fallback submit
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

        page.wait_for_timeout(5000)

    # Navigate to new post page
    try:
        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )
    except Exception:
        pass

    page.wait_for_timeout(3000)

    current = page.url

    # If still login page, failed
    if "/login" in current.lower():
        print(
            f"❌ Login failed: {current}"
        )
        return False

    # Check password form again
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
# PUBLICATION VERIFICATION
# ============================================================

def verify_publication(page, author):
    print(
        "Checking Serey publication result..."
    )

    for _ in range(15):
        page.wait_for_timeout(2000)

        current_url = page.url

        print(
            f"Current URL: {current_url}"
        )

        # The successful Serey format seen previously:
        # /authors/<username>/<generated-id>

        if re.search(
            r"/authors/[^/]+/[^/?#]+",
            current_url,
            flags=re.I,
        ):
            print(
                "✓ POST URL FOUND!"
            )
            return True

        # Sometimes redirect is delayed
        if "/blog/post/new" not in current_url:
            if "/authors/" in current_url:
                print(
                    "✓ AUTHOR POST URL FOUND!"
                )
                return True

        # Look for author post links
        try:
            links = page.locator(
                "a[href*='/authors/']"
            )

            for i in range(links.count()):
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
    author = post.get("author", "")
    permlink = post.get("permlink", "")

    title = safe_text(
        post.get("title", "")
    )

    body = clean_body(
        post.get("body", "")
    )

    category = safe_text(
        post.get("category", "")
    )

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

    image_url = extract_image(body)

    image_path = None

    if image_url:
        print(
            f"Downloading image: {image_url}"
        )

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

        page.wait_for_timeout(2500)

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
        # Make absolutely sure crop modal is closed
        if not wait_for_no_modal(page):
            print(
                "❌ Image crop modal is still blocking the page."
            )
            save_debug(page)
            return False

        # ====================================================
        # FIRST PUBLISH
        # ====================================================

        if not click_publish(
            page,
            "FIRST Publish",
        ):
            print(
                "❌ FIRST Publish button not found."
            )
            save_debug(page)
            return False

        page.wait_for_timeout(2000)

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
        # FINAL PUBLISH
        # ====================================================

        if not wait_for_no_modal(page):
            print(
                "❌ Modal still open before final Publish."
            )
            save_debug(page)
            return False

        if not click_publish(
            page,
            "FINAL Publish",
        ):
            print(
                "❌ FINAL Publish button not found."
            )
            save_debug(page)
            return False

        # ====================================================
        # VERIFY
        # ====================================================

        success = verify_publication(
            page,
            author,
        )

        if success:
            print(
                f"✓ SUCCESS: {post_id}"
            )
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
                os.remove(image_path)
            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 40)
    print("STEEMIT → BENGALI SEREY AUTO SYNC")
    print("=" * 40)

    # --------------------------------------------------------
    # CHECK ENV
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
    # LOAD SYNC
    # --------------------------------------------------------

    synced = load_synced_posts()

    print(
        f"Previously synced: {len(synced)}"
    )

    print(
        f"Permanent skipped posts: "
        f"{len(PERMANENTLY_SKIPPED)}"
    )

    # --------------------------------------------------------
    # GET STEEM POSTS
    # --------------------------------------------------------

    posts = get_all_steem_posts()

    if not posts:
        print(
            "❌ No Steem posts found."
        )
        return

    # --------------------------------------------------------
    # OLDest 1000 POSTS
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

        # Already successfully synced
        if post_id in synced:
            synced_count += 1
            continue

        unsynced.append(post)

    print(
        f"Permanent skipped posts found: "
        f"{permanent_count}"
    )

    print(
        f"Already synced posts found: "
        f"{synced_count}"
    )

    print(
        f"Unsynced posts in oldest {OLDEST_POST_LIMIT}: "
        f"{len(unsynced)}"
    )

    if not unsynced:
        print(
            "✓ Oldest 1000 queue is complete."
        )

        # IMPORTANT:
        # Do not automatically jump to newer posts.
        # This keeps the requested oldest-first queue.
        print(
            "No post will be published from outside this queue."
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
    # PLAYWRIGHT
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=HEADLESS,
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
            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            if not login_serey(page):
                print(
                    "❌ SEREY LOGIN FAILED."
                )
                return

            # ------------------------------------------------
            # PUBLISH
            # ------------------------------------------------

            for post in posts_to_publish:

                post_id = normalize_post_id(
                    post.get("author", ""),
                    post.get("permlink", ""),
                )

                success = publish_post(
                    page,
                    post,
                )

                if success:

                    # Save ONLY after real Serey URL
                    synced.add(post_id)

                    save_synced_posts(
                        synced
                    )

                    print(
                        f"✓ SAVED AS SYNCED: "
                        f"{post_id}"
                    )

                else:

                    print(
                        f"❌ FAILED: "
                        f"{post_id}"
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
    print("SYNC COMPLETED")
    print("=" * 40)


if __name__ == "__main__":
    main()
