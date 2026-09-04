import os
import json
import re
import time
import hashlib
import requests

from urllib.parse import urljoin
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError
)


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"].replace("@", "").strip()

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()

SEREY = "https://bengali.serey.io"

NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"

POSTS_PER_RUN = 1

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]

REQUEST_TIMEOUT = 25

SCREENSHOT_ON_ERROR = "serey_error.png"


# ============================================================
# GENERAL HELPERS
# ============================================================

def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_id(value):
    """
    Normalize synced IDs so old/new formats match.

    Accepted examples:
        username/permlink
        @username/permlink
        https://steemit.com/.../@username/permlink
    """

    value = safe_text(value)

    if not value:
        return ""

    value = value.strip()

    if value.startswith("@"):
        value = value[1:]

    # Full Steemit URL
    m = re.search(
        r'/@([^/\s]+)/([^/?#\s]+)',
        value
    )

    if m:
        return f"{m.group(1)}/{m.group(2)}"

    return value


def post_id(author, permlink):
    return normalize_id(
        f"{author}/{permlink}"
    )


# ============================================================
# STEEM RPC
# ============================================================

def rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }

    last_error = None

    for node in STEEM_NODES:

        try:

            print(
                f"RPC: {node}",
                flush=True
            )

            response = requests.post(
                node,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": "Steem-Serey-Auto-Sync/1.0"
                }
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise Exception(
                    data["error"]
                )

            return data["result"]

        except Exception as e:

            last_error = e

            print(
                f"RPC failed: {e}",
                flush=True
            )

            time.sleep(0.5)

    raise Exception(
        f"All Steem RPC nodes failed: {last_error}"
    )


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():

    if not os.path.exists(SYNC_FILE):

        print(
            "No synced_posts.json found.",
            flush=True
        )

        return set()

    try:

        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, list):

            print(
                "Invalid synced_posts.json format.",
                flush=True
            )

            return set()

        result = set()

        for item in data:

            normalized = normalize_id(item)

            if normalized:
                result.add(normalized)

        print(
            f"Loaded synced IDs: {len(result)}",
            flush=True
        )

        return result

    except Exception as e:

        print(
            f"Could not load sync file: {e}",
            flush=True
        )

        return set()


def save_synced(data):

    normalized = sorted(
        {
            normalize_id(x)
            for x in data
            if normalize_id(x)
        }
    )

    temp_file = SYNC_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            normalized,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp_file,
        SYNC_FILE
    )

    print(
        f"Synced file saved: {len(normalized)} IDs",
        flush=True
    )


# ============================================================
# CLEAN POST + IMAGE
# ============================================================

def clean_post(body, metadata):

    body = safe_text(body)

    image = None

    # --------------------------------------------------------
    # JSON metadata image
    # --------------------------------------------------------

    try:

        meta = json.loads(
            metadata or "{}"
        )

        images = meta.get(
            "image",
            []
        )

        if isinstance(images, str):
            images = [images]

        for item in images:

            if isinstance(item, str):

                if item.startswith("http"):

                    image = item
                    break

    except Exception:
        pass

    # --------------------------------------------------------
    # Markdown image
    # --------------------------------------------------------

    if not image:

        m = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)',
            body,
            re.I
        )

        if m:
            image = m.group(1)

    # --------------------------------------------------------
    # Remove markdown images
    # --------------------------------------------------------

    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    # --------------------------------------------------------
    # Remove standalone image URLs
    # --------------------------------------------------------

    body = re.sub(
        r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?',
        '',
        body,
        flags=re.I
    )

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    body = re.sub(
        r'\n{3,}',
        '\n\n',
        body
    )

    return body.strip(), image


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    print(
        f"Getting posts from @{STEEM_USERNAME}...",
        flush=True
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None

    page_number = 0

    while len(posts) < 5000:

        page_number += 1

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:

            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        print(
            f"Steem page {page_number}: {len(result)} posts",
            flush=True
        )

        # When using start_author/start_permlink,
        # the first result is normally the previous last post.
        batch = result

        if start_author and len(result) > 0:

            first = result[0]

            if (
                first.get("author") == start_author
                and first.get("permlink") == start_permlink
            ):
                batch = result[1:]

        if not batch:
            break

        for p in batch:

            author = safe_text(
                p.get("author")
            )

            permlink = safe_text(
                p.get("permlink")
            )

            if not author or not permlink:
                continue

            if author != STEEM_USERNAME:
                continue

            pid = post_id(
                author,
                permlink
            )

            if not pid:
                continue

            if pid in seen:
                continue

            seen.add(pid)

            body, image = clean_post(
                p.get("body", ""),
                p.get(
                    "json_metadata",
                    "{}"
                )
            )

            posts.append(
                {
                    "id": pid,
                    "title": safe_text(
                        p.get("title", "")
                    ),
                    "body": body,
                    "image": image,
                    "category": safe_text(
                        p.get("category", "")
                    ),
                    "author": author,
                    "permlink": permlink
                }
            )

        last = result[-1]

        new_author = safe_text(
            last.get("author")
        )

        new_permlink = safe_text(
            last.get("permlink")
        )

        if not new_author or not new_permlink:
            break

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

        time.sleep(0.25)

    # Oldest → newest
    posts.reverse()

    print(
        f"Total posts: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if not url:

        print(
            "No image URL.",
            flush=True
        )

        return None

    print(
        f"Downloading image: {url}",
        flush=True
    )

    # --------------------------------------------------------
    # Try original URL
    # --------------------------------------------------------

    urls = [url]

    # Some Steem/esteem image URLs can occasionally fail.
    # Do not make image mandatory.
    if "img.esteem.ws" in url:

        urls.append(
            url.replace(
                "img.esteem.ws",
                "steemitimages.com"
            )
        )

    for image_url in urls:

        try:

            print(
                f"Trying image: {image_url}",
                flush=True
            )

            r = requests.get(
                image_url,
                timeout=20,
                headers={
                    "User-Agent":
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/122 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
                }
            )

            r.raise_for_status()

            content_type = r.headers.get(
                "content-type",
                ""
            ).lower()

            if "image" not in content_type:

                print(
                    f"Not an image: {content_type}",
                    flush=True
                )

                continue

            with open(
                TEMP_IMAGE,
                "wb"
            ) as f:

                f.write(r.content)

            if os.path.getsize(
                TEMP_IMAGE
            ) < 100:

                print(
                    "Image file too small.",
                    flush=True
                )

                continue

            print(
                "✓ Image downloaded",
                flush=True
            )

            return TEMP_IMAGE

        except Exception as e:

            print(
                f"Image attempt failed: {e}",
                flush=True
            )

    print(
        "⚠️ Image unavailable. Continuing WITHOUT image.",
        flush=True
    )

    return None


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print(
        "Logging into Serey...",
        flush=True
    )

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    # --------------------------------------------------------
    # Find login button
    # --------------------------------------------------------

    login_buttons = page.locator(
        'a, button'
    ).filter(
        has_text=re.compile(
            r"^Log\s*in$",
            re.I
        )
    )

    if login_buttons.count() == 0:

        # Maybe already logged in
        print(
            "Login button not found. Checking session...",
            flush=True
        )

    else:

        login_buttons.first.click(
            force=True
        )

        page.wait_for_timeout(2500)

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    username_selectors = [
        'input[placeholder*="Username" i]',
        'input[name*="username" i]',
        'input[type="text"]'
    ]

    username_field = None

    for selector in username_selectors:

        loc = page.locator(selector)

        if loc.count() > 0:

            for i in range(loc.count()):

                item = loc.nth(i)

                try:

                    if item.is_visible():

                        username_field = item
                        break

                except Exception:
                    pass

        if username_field:
            break

    # --------------------------------------------------------
    # Private key
    # --------------------------------------------------------

    password_selectors = [
        'input[placeholder*="Private Key" i]',
        'input[placeholder*="Private" i]',
        'input[name*="private" i]',
        'input[type="password"]'
    ]

    password_field = None

    for selector in password_selectors:

        loc = page.locator(selector)

        if loc.count() > 0:

            for i in range(loc.count()):

                item = loc.nth(i)

                try:

                    if item.is_visible():

                        password_field = item
                        break

                except Exception:
                    pass

        if password_field:
            break

    if username_field and password_field:

        username_field.fill(
            SEREY_LOGIN
        )

        password_field.fill(
            SEREY_PASSWORD
        )

        print(
            "✓ Login credentials filled",
            flush=True
        )

        # Click visible login button
        buttons = page.locator("button")

        clicked = False

        for i in range(buttons.count()):

            b = buttons.nth(i)

            try:

                if not b.is_visible():
                    continue

                text = safe_text(
                    b.inner_text()
                )

                if re.fullmatch(
                    r"Log\s*in",
                    text,
                    re.I
                ):

                    b.click(
                        force=True
                    )

                    clicked = True
                    break

            except Exception:
                continue

        if not clicked:

            print(
                "⚠️ Login submit button not found.",
                flush=True
            )

        page.wait_for_timeout(6000)

    # --------------------------------------------------------
    # Verify login by opening new post page
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    current_url = page.url

    print(
        f"After login URL: {current_url}",
        flush=True
    )

    # If login form still exists visibly, login failed
    visible_private = False

    try:

        for selector in password_selectors:

            loc = page.locator(selector)

            for i in range(loc.count()):

                if loc.nth(i).is_visible():

                    visible_private = True
                    break

            if visible_private:
                break

    except Exception:
        pass

    if visible_private:

        raise Exception(
            "Serey login could not be verified."
        )

    print(
        "✓ SEREY LOGIN VERIFIED",
        flush=True
    )


# ============================================================
# CATEGORY
# ============================================================

def select_category(page, steem_category):

    steem_category = safe_text(
        steem_category
    )

    if not steem_category:

        print(
            "No Steem category.",
            flush=True
        )

        return False

    print(
        f"Steemit category: {steem_category}",
        flush=True
    )

    # --------------------------------------------------------
    # Look for category selector
    # --------------------------------------------------------

    selectors = [
        page.get_by_text(
            "Select category",
            exact=True
        ),
        page.get_by_text(
            "Select Category",
            exact=True
        )
    ]

    selector = None

    for candidate in selectors:

        try:

            if candidate.count() > 0:

                for i in range(candidate.count()):

                    item = candidate.nth(i)

                    if item.is_visible():

                        selector = item
                        break

            if selector:
                break

        except Exception:
            pass

    if not selector:

        print(
            "No category selector. Continuing.",
            flush=True
        )

        return False

    try:

        selector.click(
            force=True
        )

        page.wait_for_timeout(800)

        # Exact text
        option = page.get_by_text(
            steem_category,
            exact=True
        )

        for i in range(option.count()):

            item = option.nth(i)

            if item.is_visible():

                item.click(
                    force=True
                )

                print(
                    f"✓ Category selected: {steem_category}",
                    flush=True
                )

                return True

        # Role option
        options = page.locator(
            '[role="option"]'
        )

        for i in range(options.count()):

            item = options.nth(i)

            if not item.is_visible():
                continue

            text = safe_text(
                item.inner_text()
            )

            if text.lower() == steem_category.lower():

                item.click(
                    force=True
                )

                print(
                    f"✓ Category selected: {text}",
                    flush=True
                )

                return True

        print(
            f"Category '{steem_category}' not available.",
            flush=True
        )

    except Exception as e:

        print(
            f"Category selection skipped: {e}",
            flush=True
        )

    return False


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(page):

    names = [
        "Select sub category",
        "Select Sub Category",
        "Select sub-category"
    ]

    selector = None

    for name in names:

        try:

            candidate = page.get_by_text(
                name,
                exact=True
            )

            for i in range(candidate.count()):

                item = candidate.nth(i)

                if item.is_visible():

                    selector = item
                    break

            if selector:
                break

        except Exception:
            pass

    if not selector:

        print(
            "No Sub Category selector.",
            flush=True
        )

        return False

    try:

        selector.click(
            force=True
        )

        page.wait_for_timeout(700)

        options = page.locator(
            '[role="option"]'
        )

        for i in range(options.count()):

            item = options.nth(i)

            if item.is_visible():

                text = safe_text(
                    item.inner_text()
                )

                item.click(
                    force=True
                )

                print(
                    f"✓ Sub Category selected: {text}",
                    flush=True
                )

                return True

        print(
            "No Sub Category option available.",
            flush=True
        )

    except Exception as e:

        print(
            f"Sub Category skipped: {e}",
            flush=True
        )

    return False


# ============================================================
# UPLOAD THUMBNAIL
# ============================================================

def upload_thumbnail(page, image_file):

    if not image_file:

        print(
            "No thumbnail available. Continuing.",
            flush=True
        )

        return False

    try:

        file_inputs = page.locator(
            'input[type="file"]'
        )

        if file_inputs.count() == 0:

            print(
                "No file input found.",
                flush=True
            )

            return False

        file_input = file_inputs.first

        file_input.set_input_files(
            image_file
        )

        page.wait_for_timeout(3000)

        print(
            "✓ Thumbnail uploaded",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"Thumbnail upload skipped: {e}",
            flush=True
        )

        return False


# ============================================================
# FIND PUBLISH BUTTON
# ============================================================

def find_publish_buttons(page):

    result = []

    buttons = page.locator(
        "button"
    )

    for i in range(buttons.count()):

        b = buttons.nth(i)

        try:

            if not b.is_visible():
                continue

            text = safe_text(
                b.inner_text()
            )

            if re.fullmatch(
                r"Publish",
                text,
                re.I
            ):

                result.append(b)

        except Exception:
            continue

    return result


# ============================================================
# CLICK PUBLISH
# ============================================================

def click_publish(page, label):

    print(
        f"Searching for {label} Publish...",
        flush=True
    )

    for attempt in range(3):

        buttons = find_publish_buttons(
            page
        )

        print(
            f"Visible Publish buttons: {len(buttons)}",
            flush=True
        )

        if buttons:

            # Last Publish button is normally the
            # confirmation/final button.
            button = buttons[-1]

            try:

                button.scroll_into_view_if_needed()

            except Exception:
                pass

            try:

                button.click(
                    force=True,
                    timeout=10000
                )

                print(
                    f"✓ {label.upper()} PUBLISH CLICKED",
                    flush=True
                )

                return True

            except Exception as e:

                print(
                    f"Publish click attempt {attempt + 1} failed: {e}",
                    flush=True
                )

        page.wait_for_timeout(1500)

    return False


# ============================================================
# SUCCESS DETECTION
# ============================================================

def detect_success(page, title):

    print(
        "Checking Serey publication result...",
        flush=True
    )

    # --------------------------------------------------------
    # First check URL immediately
    # --------------------------------------------------------

    for _ in range(8):

        page.wait_for_timeout(2000)

        url = page.url

        print(
            f"Current URL: {url}",
            flush=True
        )

        if "/blog/post/new" not in url:

            if (
                "/authors/" in url
                or "/blog/" in url
                or "/post/" in url
            ):

                print(
                    "✓ SEREY POST URL DETECTED",
                    flush=True
                )

                return True

        # ----------------------------------------------------
        # Search page links
        # ----------------------------------------------------

        try:

            links = page.locator(
                "a[href]"
            )

            for i in range(
                min(links.count(), 300)
            ):

                link = links.nth(i)

                if not link.is_visible():
                    continue

                href = link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                full_url = urljoin(
                    SEREY,
                    href
                )

                if (
                    "/authors/" in full_url
                    or "/blog/" in full_url
                ):

                    text = safe_text(
                        link.inner_text()
                    )

                    if (
                        title.lower()
                        in text.lower()
                        or text
                    ):

                        print(
                            f"✓ Possible published URL: {full_url}",
                            flush=True
                        )

                        return True

        except Exception:
            pass

        # ----------------------------------------------------
        # Search visible success messages
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            success_words = [
                "published successfully",
                "publish successfully",
                "successfully published",
                "post published",
                "published"
            ]

            lower_body = body_text.lower()

            for word in success_words:

                if word in lower_body:

                    print(
                        f"✓ Success message detected: {word}",
                        flush=True
                    )

                    return True

        except Exception:
            pass

    # --------------------------------------------------------
    # Final title check
    # --------------------------------------------------------

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        if (
            title
            and title.lower()
            in body_text.lower()
            and "/blog/post/new" not in page.url
        ):

            print(
                "✓ Post title detected after publishing.",
                flush=True
            )

            return True

    except Exception:
        pass

    print(
        "❌ Publication could not be verified.",
        flush=True
    )

    return False


# ============================================================
# SAVE DEBUG INFORMATION
# ============================================================

def save_debug(page):

    try:

        page.screenshot(
            path=SCREENSHOT_ON_ERROR,
            full_page=True
        )

        print(
            f"Debug screenshot saved: {SCREENSHOT_ON_ERROR}",
            flush=True
        )

    except Exception as e:

        print(
            f"Could not save screenshot: {e}",
            flush=True
        )

    try:

        with open(
            "serey_error.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                page.content()
            )

        print(
            "Debug HTML saved: serey_error.html",
            flush=True
        )

    except Exception as e:

        print(
            f"Could not save debug HTML: {e}",
            flush=True
        )


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish(page, post):

    print("-" * 60)

    print(
        f"Publishing: {post['title']}",
        flush=True
    )

    # --------------------------------------------------------
    # Open new post
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    print(
        f"New post URL: {page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_fields = page.locator(
        'input[placeholder*="Title" i]'
    )

    if title_fields.count() == 0:

        raise Exception(
            "Title input not found."
        )

    title = title_fields.first

    title.fill(
        post["title"]
    )

    print(
        "✓ Title filled",
        flush=True
    )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    editors = page.locator(
        'div[contenteditable="true"]'
    )

    if editors.count() == 0:

        raise Exception(
            "Post editor not found."
        )

    editor = editors.first

    editor.click()

    editor.fill(
        post["body"]
    )

    print(
        "✓ Body filled",
        flush=True
    )

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image = download_image(
        post.get("image")
    )

    if image:

        upload_thumbnail(
            page,
            image
        )

    else:

        print(
            "✓ Continuing without thumbnail.",
            flush=True
        )

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    first_publish = click_publish(
        page,
        "FIRST"
    )

    if not first_publish:

        save_debug(page)

        raise Exception(
            "FIRST Publish button not found."
        )

    # --------------------------------------------------------
    # Wait for next UI state
    # --------------------------------------------------------

    page.wait_for_timeout(3000)

    print(
        f"URL after first Publish: {page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    select_category(
        page,
        post.get("category", "")
    )

    # --------------------------------------------------------
    # SUB CATEGORY
    # --------------------------------------------------------

    select_subcategory(
        page
    )

    # --------------------------------------------------------
    # FINAL PUBLISH
    # --------------------------------------------------------

    page.wait_for_timeout(1000)

    final_publish = click_publish(
        page,
        "FINAL"
    )

    if not final_publish:

        # Sometimes the first Publish is actually the
        # final submission. Give the page a chance to
        # redirect/show success before declaring failure.

        print(
            "No second Publish button found. Checking result...",
            flush=True
        )

        if detect_success(
            page,
            post["title"]
        ):

            return True

        save_debug(page)

        return False

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    success = detect_success(
        page,
        post["title"]
    )

    if not success:

        save_debug(page)

        return False

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("STEEM -> SEREY AUTO SYNC")
    print("=" * 60)

    # --------------------------------------------------------
    # Environment check
    # --------------------------------------------------------

    if not SEREY_LOGIN:

        raise Exception(
            "SEREY_LOGIN / SEREY_USERNAME is missing."
        )

    if not SEREY_PASSWORD:

        raise Exception(
            "SEREY_PASSWORD is missing."
        )

    # --------------------------------------------------------
    # Load synced
    # --------------------------------------------------------

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    # --------------------------------------------------------
    # Get Steem posts
    # --------------------------------------------------------

    posts = get_posts()

    # --------------------------------------------------------
    # Find unsynced
    # --------------------------------------------------------

    new_posts = []

    for post in posts:

        pid = normalize_id(
            post["id"]
        )

        if pid not in synced:

            new_posts.append(
                post
            )

    print(
        f"Unsynced posts: {len(new_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # Only configured number
    # --------------------------------------------------------

    posts_to_run = new_posts[
        :POSTS_PER_RUN
    ]

    print(
        f"Publishing this run: {len(posts_to_run)}",
        flush=True
    )

    if not posts_to_run:

        print(
            "Nothing to publish.",
            flush=True
        )

        return

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1280,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            login(page)

            # ------------------------------------------------
            # PUBLISH
            # ------------------------------------------------

            for post in posts_to_run:

                try:

                    success = publish(
                        page,
                        post
                    )

                    if success:

                        synced.add(
                            normalize_id(
                                post["id"]
                            )
                        )

                        save_synced(
                            synced
                        )

                        print(
                            f"✓ SAVED AS SYNCED: {post['id']}",
                            flush=True
                        )

                    else:

                        print(
                            "⚠️ NOT SAVED AS SYNCED.",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publish error: {e}",
                        flush=True
                    )

                    try:
                        save_debug(page)
                    except Exception:
                        pass

        finally:

            # ------------------------------------------------
            # Remove temporary image
            # ------------------------------------------------

            if os.path.exists(
                TEMP_IMAGE
            ):

                try:

                    os.remove(
                        TEMP_IMAGE
                    )

                except Exception:
                    pass

            # ------------------------------------------------
            # Close browser
            # ------------------------------------------------

            try:

                context.close()

            except Exception:
                pass

            try:

                browser.close()

            except Exception:
                pass

    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
