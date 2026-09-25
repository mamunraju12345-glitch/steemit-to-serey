import os
import re
import json
import time
import html
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

STEEM_USERNAME = os.environ.get("STEEM_USERNAME", "").strip()
SEREY_LOGIN = os.environ.get("SEREY_LOGIN", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY_BASE = "https://bengali.serey.io"
SEREY_NEW_POST = f"{SEREY_BASE}/blog/post/new"

DAYS_LIMIT = 365
POSTS_PER_RUN = 1

SYNC_FILE = "synced_posts.json"

MAX_IMAGE_SIZE = 30 * 1024 * 1024

RPC_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    if url.startswith("/"):
        url = urljoin(SEREY_BASE, url)

    return url.rstrip("/")


def is_real_post_url(url):
    if not url:
        return False

    url = normalize_url(url)

    try:
        parsed = urlparse(url)
        base = urlparse(SEREY_BASE)

        if parsed.netloc.lower() != base.netloc.lower():
            return False

        prefix = f"/authors/{SEREY_LOGIN.lower()}/"

        return (
            parsed.path.lower().startswith(prefix)
            and len(parsed.path) > len(prefix)
        )

    except Exception:
        return False


# ============================================================
# STEEM RPC
# ============================================================

def rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    for node in RPC_NODES:

        try:

            response = requests.post(
                node,
                json=payload,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            if response.status_code == 200:

                data = response.json()

                if "result" in data:

                    print(
                        f"✓ RPC success: {node}"
                    )

                    return data["result"]

        except Exception:
            continue

    raise RuntimeError(
        "All Steem RPC nodes failed."
    )


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():

    if not os.path.exists(SYNC_FILE):
        return set()

    try:

        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        if isinstance(data, dict):
            return set(data.keys())

    except Exception as e:

        print(
            f"⚠ Could not read {SYNC_FILE}: {e}"
        )

    return set()


def save_synced(synced):

    with open(
        SYNC_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(list(synced)),
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# STEEM DATE
# ============================================================

def parse_steem_date(value):

    try:

        return datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%S"
        ).replace(
            tzinfo=timezone.utc
        )

    except Exception:

        return None


# ============================================================
# THUMBNAIL + BODY
# ============================================================

def extract_thumbnail_and_body(post):

    body = post.get("body", "") or ""

    metadata = post.get(
        "json_metadata",
        ""
    )

    try:

        if isinstance(metadata, str):
            metadata = json.loads(metadata)

    except Exception:

        metadata = {}

    thumbnail = None

    # Metadata images
    if isinstance(metadata, dict):

        images = metadata.get(
            "image",
            []
        )

        if isinstance(images, str):
            images = [images]

        if isinstance(images, list):

            for image in images:

                if (
                    isinstance(image, str)
                    and image.startswith("http")
                ):

                    thumbnail = image
                    break

        # Other possible thumbnail fields
        if not thumbnail:

            for key in [
                "cover",
                "thumbnail",
                "cover_image"
            ]:

                value = metadata.get(key)

                if (
                    isinstance(value, str)
                    and value.startswith("http")
                ):

                    thumbnail = value
                    break

    # First image in body
    if not thumbnail:

        match = re.search(
            r'https?://[^\s)"\'<>]+?\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s)"\'<>]*)?',
            body,
            re.IGNORECASE
        )

        if match:
            thumbnail = match.group(0)

    # Clean body
    clean_body = body

    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )

    clean_body = re.sub(
        r'<img[^>]*>',
        '',
        clean_body,
        flags=re.IGNORECASE
    )

    clean_body = re.sub(
        r'https?://[^\s)"\'<>]+?\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s)"\'<>]*)?',
        '',
        clean_body,
        flags=re.IGNORECASE
    )

    clean_body = re.sub(
        r'<[^>]+>',
        '',
        clean_body
    )

    clean_body = html.unescape(
        clean_body
    )

    clean_body = re.sub(
        r'\n\s*\n\s*\n+',
        '\n\n',
        clean_body
    )

    return thumbnail, clean_body.strip()


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=DAYS_LIMIT)
    )

    print(
        f"Collecting posts from @{STEEM_USERNAME} "
        f"for the last {DAYS_LIMIT} days..."
    )

    print(
        f"Post cut-off date: "
        f"{cutoff.strftime('%Y-%m-%d')}"
    )

    posts = []

    start = -1
    batch_size = 1000

    while True:

        result = rpc(
            "condenser_api.get_account_history",
            [
                STEEM_USERNAME,
                start,
                batch_size
            ]
        )

        if not result:
            break

        stop = False

        for item in result:

            if (
                not isinstance(item, list)
                or len(item) != 2
            ):
                continue

            index, operation = item

            try:

                op_type = operation[0]
                data = operation[1]

            except Exception:

                continue

            if op_type != "comment":
                continue

            if data.get("author") != STEEM_USERNAME:
                continue

            # Only root posts
            if data.get("parent_author"):
                continue

            created = parse_steem_date(
                data.get("created", "")
            )

            if not created:
                continue

            if created < cutoff:

                stop = True
                continue

            permlink = data.get(
                "permlink",
                ""
            )

            if not permlink:
                continue

            thumbnail, clean_body = (
                extract_thumbnail_and_body(data)
            )

            posts.append({
                "author": STEEM_USERNAME,
                "permlink": permlink,
                "title": data.get(
                    "title",
                    ""
                ).strip(),
                "body": clean_body,
                "thumbnail": thumbnail,
                "created": data.get(
                    "created",
                    ""
                ),
                "identifier": (
                    f"{STEEM_USERNAME}/"
                    f"{permlink}"
                )
            })

        if stop:
            break

        if len(result) < batch_size:
            break

        start = result[0][0] - 1

        if start < 0:
            break

    # Remove duplicates
    unique = {}

    for post in posts:
        unique[
            post["identifier"]
        ] = post

    posts = list(
        unique.values()
    )

    # Oldest -> newest
    posts.sort(
        key=lambda x: x["created"]
    )

    print(
        f"Total posts collected from the last "
        f"{DAYS_LIMIT} days: {len(posts)}"
    )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if not url:
        return None

    print(
        f"Downloading cover thumbnail: {url}"
    )

    try:

        response = requests.get(
            url,
            timeout=60,
            stream=True,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if response.status_code != 200:

            print(
                f"❌ Image download failed: "
                f"HTTP {response.status_code}"
            )

            return None

        filename = "temp_image.jpg"

        total = 0

        with open(
            filename,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=128 * 1024
            ):

                if not chunk:
                    continue

                total += len(chunk)

                if total > MAX_IMAGE_SIZE:

                    print(
                        "❌ Image exceeded 30 MB."
                    )

                    try:
                        os.remove(filename)
                    except Exception:
                        pass

                    return None

                f.write(chunk)

        print(
            f"✓ Cover image saved: "
            f"{filename} ({total} bytes)"
        )

        return filename

    except Exception as e:

        print(
            f"❌ Image download error: {e}"
        )

        return None


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print(
        "Logging into Serey..."
    )

    for attempt in range(1, 4):

        print(
            f"--- Login Attempt {attempt}/3 ---"
        )

        try:

            page.goto(
                SEREY_BASE,
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(
                2500
            )

            # Existing session
            if (
                page.locator(
                    "input[type='password']"
                ).count() == 0
                and (
                    "/login"
                    not in page.url.lower()
                )
            ):

                print(
                    "✓ Detected existing session! "
                    "Already logged in."
                )

                return True

            # Login button
            login_buttons = page.locator(
                "button:has-text('Login'), "
                "button:has-text('Log in'), "
                "a:has-text('Login'), "
                "a:has-text('Log in')"
            )

            if login_buttons.count() == 0:

                print(
                    "Login button not found."
                )

                continue

            login_buttons.first.click()

            page.wait_for_timeout(
                1500
            )

            username_input = page.locator(
                "input[name='username'], "
                "input[name='login'], "
                "input[type='text']"
            ).first

            password_input = page.locator(
                "input[type='password']"
            ).first

            if (
                username_input.count() == 0
                or password_input.count() == 0
            ):

                print(
                    "Login fields not found."
                )

                continue

            username_input.fill(
                SEREY_LOGIN
            )

            password_input.fill(
                SEREY_PASSWORD
            )

            page.locator(
                "button[type='submit'], "
                "button:has-text('Login'), "
                "button:has-text('Log in')"
            ).last.click()

            page.wait_for_timeout(
                5000
            )

            if "/login" not in page.url.lower():

                print(
                    "✓ Login successful."
                )

                return True

        except Exception as e:

            print(
                f"Login error: {e}"
            )

    print(
        "❌ Serey login failed."
    )

    return False


# ============================================================
# NETWORK CAPTURE
# ============================================================

class NetworkCapture:

    def __init__(self, page):

        self.responses = []

        page.on(
            "response",
            self._handle_response
        )

    def _handle_response(self, response):

        try:

            url = response.url

            if (
                "/api/" in url.lower()
                or "graphql" in url.lower()
                or "/post" in url.lower()
                or "/blog" in url.lower()
                or "/author" in url.lower()
            ):

                self.responses.append({
                    "url": url,
                    "status": response.status
                })

                if len(self.responses) > 300:

                    self.responses = (
                        self.responses[-300:]
                    )

        except Exception:
            pass


# ============================================================
# FIND POST URL
# ============================================================

def find_real_post_links(page):

    links = set()

    try:

        anchors = page.locator(
            "a[href]"
        )

        count = min(
            anchors.count(),
            500
        )

        for i in range(count):

            try:

                href = anchors.nth(i).get_attribute(
                    "href"
                )

                if not href:
                    continue

                href = normalize_url(href)

                if is_real_post_url(href):

                    links.add(href)

            except Exception:
                continue

    except Exception:
        pass

    return links


# ============================================================
# VERIFY POST
# ============================================================

def verify_post(page, url, expected_title):

    if not is_real_post_url(url):
        return False

    try:

        print(
            f"Checking post URL: {url}"
        )

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=20000
        )

        page.wait_for_timeout(
            2000
        )

        if not is_real_post_url(page.url):

            return False

        expected = normalize_text(
            expected_title
        )

        if not expected:

            return True

        texts = []

        # Browser title
        try:

            browser_title = page.title()

            if browser_title:
                texts.append(
                    browser_title
                )

        except Exception:
            pass

        # Headings
        for selector in [
            "h1",
            "h2",
            "article h1",
            "article h2"
        ]:

            try:

                locator = page.locator(
                    selector
                )

                count = min(
                    locator.count(),
                    10
                )

                for i in range(count):

                    try:

                        text = locator.nth(i).inner_text(
                            timeout=1500
                        )

                        if text:
                            texts.append(text)

                    except Exception:
                        pass

            except Exception:
                pass

        # Body fallback
        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=4000
            )

            if body_text:

                texts.append(
                    body_text[:25000]
                )

        except Exception:
            pass

        normalized = [
            normalize_text(x)
            for x in texts
            if x
        ]

        # Exact title
        for text in normalized:

            if expected in text:

                print(
                    "✓ Post title verified."
                )

                return True

        # Word match
        words = [
            w
            for w in re.findall(
                r"[a-z0-9]+",
                expected
            )
            if len(w) >= 3
        ]

        if len(words) >= 3:

            for text in normalized:

                matches = sum(
                    1
                    for word in words
                    if word in text
                )

                if (
                    matches >= 3
                    and matches / len(words) >= 0.55
                ):

                    print(
                        "✓ Post title partially verified."
                    )

                    return True

    except Exception as e:

        print(
            f"Post verification error: {e}"
        )

    return False


# ============================================================
# CHECK EXISTING POST
# ============================================================

def check_existing_post(page, post):

    permlink = post.get(
        "permlink",
        ""
    )

    if not permlink:
        return None

    expected_url = (
        f"{SEREY_BASE}/authors/"
        f"{SEREY_LOGIN}/"
        f"{permlink}"
    )

    print(
        "Checking if this post already exists..."
    )

    print(
        f"Expected URL: {expected_url}"
    )

    try:

        if verify_post(
            page,
            expected_url,
            post["title"]
        ):

            print(
                "✓ Existing Serey post found."
            )

            return expected_url

    except Exception:
        pass

    print(
        "✓ Existing post not found."
    )

    return None


# ============================================================
# FIRST PUBLISH
# ============================================================

def click_first_publish(page):

    print(
        "Attempting to click first Publish..."
    )

    selectors = [
        "button:has-text('Publish')",
        "button:has-text('Publish Post')",
        "button:has-text('পাবলিশ')"
    ]

    for selector in selectors:

        try:

            buttons = page.locator(
                selector
            )

            count = buttons.count()

            for i in range(
                count - 1,
                -1,
                -1
            ):

                try:

                    button = buttons.nth(i)

                    if not button.is_visible():
                        continue

                    button.scroll_into_view_if_needed()

                    button.click(
                        timeout=10000
                    )

                    page.wait_for_timeout(
                        1500
                    )

                    print(
                        "✓ Publish modal opened."
                    )

                    return True

                except Exception:
                    continue

        except Exception:
            continue

    print(
        "❌ First Publish button not found."
    )

    return False


# ============================================================
# FINAL PUBLISH
# ============================================================

def find_final_publish_button(page):

    selectors = [
        ".ant-modal:visible "
        "button:has-text('Publish')",

        ".ant-modal:visible "
        "button[type='submit']",

        "[role='dialog']:visible "
        "button:has-text('Publish')",

        "[role='dialog']:visible "
        "button[type='submit']"
    ]

    for selector in selectors:

        try:

            buttons = page.locator(
                selector
            )

            count = buttons.count()

            for i in range(
                count - 1,
                -1,
                -1
            ):

                try:

                    button = buttons.nth(i)

                    if button.is_visible():

                        return button

                except Exception:
                    continue

        except Exception:
            continue

    return None


def click_final_publish(page):

    print(
        "Searching for final Publish button..."
    )

    # Give modal a short time to render
    page.wait_for_timeout(
        1000
    )

    button = find_final_publish_button(
        page
    )

    if button is None:

        print(
            "❌ Final Publish button not found."
        )

        return False

    try:

        button.scroll_into_view_if_needed()

        # Wait maximum 10 seconds for enabled state
        start = time.time()

        while time.time() - start < 10:

            try:

                if not button.is_disabled():
                    break

            except Exception:
                pass

            page.wait_for_timeout(
                500
            )

        try:

            if button.is_disabled():

                print(
                    "❌ Final Publish button "
                    "is disabled."
                )

                return False

        except Exception:
            pass

        # IMPORTANT:
        # Only ONE click.
        button.click(
            timeout=10000
        )

        print(
            "✓ Final Publish button clicked once."
        )

        return True

    except Exception as e:

        print(
            f"❌ Final Publish click failed: {e}"
        )

        return False


# ============================================================
# SAVE DEBUG
# ============================================================

def save_debug(page):

    timestamp = int(
        time.time()
    )

    html_file = (
        f"serey_debug_{timestamp}.html"
    )

    png_file = (
        f"serey_debug_{timestamp}.png"
    )

    try:

        with open(
            html_file,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                page.content()
            )

        print(
            f"✓ Debug HTML saved: {html_file}"
        )

    except Exception as e:

        print(
            f"Debug HTML error: {e}"
        )

    try:

        page.screenshot(
            path=png_file,
            full_page=True
        )

        print(
            f"✓ Debug screenshot saved: {png_file}"
        )

    except Exception:
        pass


# ============================================================
# PUBLISH
# ============================================================

def publish(page, capture, post):

    print("-" * 60)

    print(
        f"Publishing: {post['title']} "
        f"(Steem Date: {post['created']})"
    )

    # --------------------------------------------------------
    # DUPLICATE CHECK
    # --------------------------------------------------------

    existing = check_existing_post(
        page,
        post
    )

    if existing:

        return existing

    # --------------------------------------------------------
    # OPEN NEW POST
    # --------------------------------------------------------

    try:

        page.goto(
            SEREY_NEW_POST,
            wait_until="domcontentloaded",
            timeout=30000
        )

        page.wait_for_timeout(
            2000
        )

    except Exception as e:

        print(
            f"❌ Could not open new post page: {e}"
        )

        return None

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    try:

        title = page.locator(
            "input[name='title'], "
            "input[placeholder*='Title' i], "
            "textarea[placeholder*='Title' i]"
        ).first

        if title.count() == 0:

            print(
                "❌ Title field not found."
            )

            return None

        title.fill(
            post["title"]
        )

        print(
            "✓ Title filled"
        )

    except Exception as e:

        print(
            f"❌ Title error: {e}"
        )

        return None

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    try:

        body = post.get(
            "body",
            ""
        )

        editor = page.locator(
            "[contenteditable='true']"
        ).first

        if editor.count() == 0:

            editor = page.locator(
                "textarea"
            ).last

        if editor.count() == 0:

            print(
                "❌ Body editor not found."
            )

            return None

        try:

            editor.fill(
                body
            )

        except Exception:

            editor.click()

            page.keyboard.insert_text(
                body
            )

        print(
            f"✓ Body filled "
            f"({len(body)} characters)"
        )

    except Exception as e:

        print(
            f"❌ Body error: {e}"
        )

        return None

    # --------------------------------------------------------
    # THUMBNAIL
    # --------------------------------------------------------

    image_file = None

    try:

        if post.get("thumbnail"):

            image_file = download_image(
                post["thumbnail"]
            )

            if image_file:

                inputs = page.locator(
                    "input[type='file']"
                )

                if inputs.count() > 0:

                    uploaded = False

                    for i in range(
                        inputs.count()
                    ):

                        try:

                            inputs.nth(i).set_input_files(
                                image_file
                            )

                            page.wait_for_timeout(
                                2000
                            )

                            print(
                                "✓ Thumbnail uploaded."
                            )

                            uploaded = True
                            break

                        except Exception:
                            continue

                    if not uploaded:

                        print(
                            "⚠ Thumbnail upload "
                            "failed."
                        )

                else:

                    print(
                        "⚠ File input not found."
                    )

    except Exception as e:

        print(
            f"⚠ Thumbnail error: {e}"
        )

    # --------------------------------------------------------
    # CROP
    # --------------------------------------------------------

    try:

        page.wait_for_timeout(
            1500
        )

        buttons = page.locator(
            "button:has-text('Confirm'), "
            "button:has-text('Done'), "
            "button:has-text('Save'), "
            "button:has-text('OK')"
        )

        if buttons.count() > 0:

            for i in range(
                buttons.count() - 1,
                -1,
                -1
            ):

                try:

                    button = buttons.nth(i)

                    if button.is_visible():

                        button.click(
                            timeout=5000
                        )

                        print(
                            "✓ Thumbnail processing finished."
                        )

                        page.wait_for_timeout(
                            1000
                        )

                        break

                except Exception:
                    continue

    except Exception:
        pass

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    if not click_first_publish(page):

        save_debug(page)

        return None

    # ========================================================
    # NO CATEGORY
    # ========================================================
    #
    # IMPORTANT:
    # We intentionally do NOT touch the category dropdown.
    #
    # ========================================================

    print(
        "✓ Skipping Category selection."
    )

    page.wait_for_timeout(
        1000
    )

    # --------------------------------------------------------
    # FINAL PUBLISH
    # --------------------------------------------------------

    if not click_final_publish(page):

        save_debug(page)

        return None

    # --------------------------------------------------------
    # WAIT FOR PUBLISH
    # --------------------------------------------------------

    print(
        "Waiting for Serey to create the post..."
    )

    expected_url = (
        f"{SEREY_BASE}/authors/"
        f"{SEREY_LOGIN}/"
        f"{post['permlink']}"
    )

    # --------------------------------------------------------
    # CHECK CURRENT URL
    # --------------------------------------------------------

    for attempt in range(
        1,
        9
    ):

        print(
            f"Verification attempt "
            f"{attempt}/8..."
        )

        page.wait_for_timeout(
            3000
        )

        # Current browser URL
        try:

            current_url = page.url

            if is_real_post_url(
                current_url
            ):

                if verify_post(
                    page,
                    current_url,
                    post["title"]
                ):

                    print(
                        "✓ PUBLISH VERIFIED:"
                    )

                    print(
                        current_url
                    )

                    return current_url

        except Exception:
            pass

        # Expected permlink URL
        try:

            if verify_post(
                page,
                expected_url,
                post["title"]
            ):

                print(
                    "✓ PUBLISH VERIFIED:"
                )

                print(
                    expected_url
                )

                return expected_url

        except Exception:
            pass

        # Network URL candidates
        try:

            candidates = set()

            for item in capture.responses:

                url = item.get(
                    "url",
                    ""
                )

                if is_real_post_url(url):

                    candidates.add(url)

            for candidate in candidates:

                if verify_post(
                    page,
                    candidate,
                    post["title"]
                ):

                    print(
                        "✓ PUBLISH VERIFIED:"
                    )

                    print(
                        candidate
                    )

                    return candidate

        except Exception:
            pass

    # --------------------------------------------------------
    # FINAL EXPECTED URL CHECK
    # --------------------------------------------------------

    print(
        "Final post URL check..."
    )

    try:

        if verify_post(
            page,
            expected_url,
            post["title"]
        ):

            print(
                "✓ PUBLISH VERIFIED:"
            )

            print(
                expected_url
            )

            return expected_url

    except Exception:
        pass

    print(
        "❌ PUBLISH COULD NOT BE VERIFIED."
    )

    save_debug(page)

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        "STEEM -> BENGALI SEREY AUTO SYNC"
    )

    print(
        "LAST 365 DAYS -> OLDEST TO NEWEST"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # CHECK SECRETS
    # --------------------------------------------------------

    if not STEEM_USERNAME:

        raise RuntimeError(
            "STEEM_USERNAME secret is missing."
        )

    if not SEREY_LOGIN:

        raise RuntimeError(
            "SEREY_LOGIN secret is missing."
        )

    if not SEREY_PASSWORD:

        raise RuntimeError(
            "SEREY_PASSWORD secret is missing."
        )

    # --------------------------------------------------------
    # SYNC STATE
    # --------------------------------------------------------

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}"
    )

    # --------------------------------------------------------
    # GET POSTS
    # --------------------------------------------------------

    posts = get_posts()

    unsynced = [
        post
        for post in posts
        if post["identifier"]
        not in synced
    ]

    print(
        f"Unsynced posts remaining "
        f"(Last 1 Year): {len(unsynced)}"
    )

    if not unsynced:

        print(
            "✓ No unsynced posts remaining."
        )

        print("=" * 60)
        print("RUN FINISHED")
        print("=" * 60)

        return

    # Oldest first
    selected = unsynced[
        :POSTS_PER_RUN
    ]

    for post in selected:

        print(
            f"Selected: "
            f"{post['identifier']}"
        )

        print(
            f"Created: "
            f"{post['created']}"
        )

    # --------------------------------------------------------
    # PLAYWRIGHT
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000
            },
            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        # Start network capture immediately
        capture = NetworkCapture(
            page
        )

        try:

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            if not login(page):

                print(
                    "❌ Login failed."
                )

                return

            # ------------------------------------------------
            # PUBLISH ONE POST
            # ------------------------------------------------

            for post in selected:

                result = publish(
                    page,
                    capture,
                    post
                )

                if result:

                    synced.add(
                        post["identifier"]
                    )

                    save_synced(
                        synced
                    )

                    print(
                        f"✓ Added to "
                        f"synced_posts.json: "
                        f"{post['identifier']}"
                    )

                else:

                    print(
                        f"⚠ FAILED: "
                        f"{post['identifier']}"
                    )

                    print(
                        "⚠ This post will NOT be "
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

    print("=" * 60)
    print("RUN FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
