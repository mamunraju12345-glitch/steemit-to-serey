import os
import re
import json
import time
import html
import hashlib
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIG
# ============================================================

STEEM_USERNAME = os.environ.get("STEEM_USERNAME", "").strip()
SEREY_LOGIN = os.environ.get("SEREY_LOGIN", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY_BASE = "https://bengali.serey.io"
SEREY_NEW_POST = f"{SEREY_BASE}/blog/post/new"

POSTS_PER_RUN = 1
DAYS_LIMIT = 365

SYNC_FILE = "synced_posts.json"

MAX_IMAGE_SIZE = 30 * 1024 * 1024

RPC_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]


# ============================================================
# BASIC HELPERS
# ============================================================

def remove_overlays(page):
    try:
        page.evaluate("""
        () => {
            const selectors = [
                '.intercom-lightweight-app',
                '#intercom-container',
                '[class*="cookie"]',
                '[id*="cookie"]'
            ];

            for (const selector of selectors) {
                document.querySelectorAll(selector).forEach(el => {
                    try {
                        el.remove();
                    } catch(e) {}
                });
            }
        }
        """)
    except Exception:
        pass


def normalize_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    if url.startswith("/"):
        url = urljoin(SEREY_BASE, url)

    return url


def is_real_post_url(url):
    if not url:
        return False

    url = normalize_url(url)

    parsed = urlparse(url)

    if parsed.netloc.lower() != urlparse(SEREY_BASE).netloc.lower():
        return False

    path = parsed.path.rstrip("/")

    expected_prefix = f"/authors/{SEREY_LOGIN.lower()}/"

    return path.lower().startswith(expected_prefix) and len(path) > len(expected_prefix)


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
            r = requests.post(
                node,
                json=payload,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            if r.status_code == 200:
                data = r.json()

                if "result" in data:
                    print(f"✓ RPC success: {node}")
                    return data["result"]

        except Exception:
            continue

    raise RuntimeError("All Steem RPC nodes failed.")


# ============================================================
# SYNC STATE
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        if isinstance(data, dict):
            return set(data.keys())

    except Exception as e:
        print(f"Could not read {SYNC_FILE}: {e}")

    return set()


def save_synced(synced):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(list(synced)),
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# STEEM POST EXTRACTION
# ============================================================

def parse_steem_date(value):
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def extract_thumbnail_and_body(post):
    body = post.get("body", "") or ""
    metadata = post.get("json_metadata", "")

    try:
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
    except Exception:
        metadata = {}

    thumbnail = None

    # Try metadata images first
    if isinstance(metadata, dict):
        images = metadata.get("image", [])

        if isinstance(images, str):
            images = [images]

        if isinstance(images, list):
            for img in images:
                if isinstance(img, str) and img.startswith("http"):
                    thumbnail = img
                    break

        # Some posts use cover / thumbnail
        if not thumbnail:
            for key in ["cover", "thumbnail", "cover_image"]:
                value = metadata.get(key)

                if isinstance(value, str) and value.startswith("http"):
                    thumbnail = value
                    break

    # Find first image in body
    if not thumbnail:
        match = re.search(
            r'https?://[^\s\)"\'<>]+?\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s\)"\'<>]*)?',
            body,
            re.IGNORECASE
        )

        if match:
            thumbnail = match.group(0)

    # Clean body
    clean_body = body

    # Remove markdown images
    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )

    # Remove HTML images
    clean_body = re.sub(
        r'<img[^>]*>',
        '',
        clean_body,
        flags=re.IGNORECASE
    )

    # Remove raw image URLs
    clean_body = re.sub(
        r'https?://[^\s\)"\'<>]+?\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s\)"\'<>]*)?',
        '',
        clean_body,
        flags=re.IGNORECASE
    )

    # Remove some HTML
    clean_body = re.sub(
        r'<[^>]+>',
        '',
        clean_body
    )

    clean_body = html.unescape(clean_body)

    # Normalize excessive blank lines
    clean_body = re.sub(r'\n\s*\n\s*\n+', '\n\n', clean_body)
    clean_body = clean_body.strip()

    return thumbnail, clean_body


def get_posts():
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_LIMIT)

    print(
        f"Collecting posts from @{STEEM_USERNAME} "
        f"for the last {DAYS_LIMIT} days..."
    )

    print(
        f"Post cut-off date: {cutoff.strftime('%Y-%m-%d')}"
    )

    posts = []

    # Get account history in batches
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
            if not isinstance(item, list) or len(item) != 2:
                continue

            index, operation = item

            try:
                op_type = operation[0]
                op_data = operation[1]
            except Exception:
                continue

            if op_type != "comment":
                continue

            author = op_data.get("author", "")
            if author != STEEM_USERNAME:
                continue

            created = parse_steem_date(
                op_data.get("created", "")
            )

            if not created:
                continue

            if created < cutoff:
                stop = True
                continue

            parent_author = op_data.get("parent_author", "")

            # Only root posts
            if parent_author:
                continue

            permlink = op_data.get("permlink", "")

            if not permlink:
                continue

            thumbnail, clean_body = extract_thumbnail_and_body(op_data)

            posts.append({
                "author": author,
                "permlink": permlink,
                "title": op_data.get("title", "").strip(),
                "body": clean_body,
                "thumbnail": thumbnail,
                "created": op_data.get("created", ""),
                "identifier": f"{author}/{permlink}"
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
        unique[post["identifier"]] = post

    posts = list(unique.values())

    # Oldest first
    posts.sort(
        key=lambda x: x.get("created", "")
    )

    print(
        f"Total posts collected from the last {DAYS_LIMIT} days: "
        f"{len(posts)}"
    )

    return posts


# ============================================================
# IMAGE
# ============================================================

def download_image(url):
    if not url:
        return None

    print(f"Downloading cover thumbnail: {url}")

    try:
        r = requests.get(
            url,
            timeout=60,
            stream=True,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if r.status_code != 200:
            print(f"❌ Image download failed: HTTP {r.status_code}")
            return None

        content_length = r.headers.get("content-length")

        if content_length:
            try:
                if int(content_length) > MAX_IMAGE_SIZE:
                    print("❌ Image is too large.")
                    return None
            except Exception:
                pass

        filename = "temp_image.jpg"

        total = 0

        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue

                total += len(chunk)

                if total > MAX_IMAGE_SIZE:
                    print("❌ Image exceeded maximum size.")
                    try:
                        os.remove(filename)
                    except Exception:
                        pass
                    return None

                f.write(chunk)

        print(
            f"✓ Cover image saved: {filename} ({total} bytes)"
        )

        return filename

    except Exception as e:
        print(f"❌ Image download error: {e}")
        return None


# ============================================================
# LOGIN
# ============================================================

def login(page):
    print("Logging into Serey...")

    for attempt in range(1, 4):
        print(f"--- Login Attempt {attempt}/3 ---")

        try:
            page.goto(
                SEREY_BASE,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(3000)

            # Already logged in
            if page.locator(
                "text=Logout, text=Sign out, text=Log out"
            ).count() > 0:
                print("✓ Detected existing session! Already logged in.")
                return True

            # Check if user profile/session exists
            current = page.url.lower()

            if "/blog" in current and (
                page.locator("input[type='password']").count() == 0
            ):
                print("✓ Existing Serey session detected.")
                return True

            # Login button
            login_buttons = page.locator(
                "button:has-text('Login'), "
                "button:has-text('Log in'), "
                "a:has-text('Login'), "
                "a:has-text('Log in')"
            )

            if login_buttons.count() == 0:
                print("Login button not found.")
                continue

            login_buttons.first.click()

            page.wait_for_timeout(2000)

            user_input = page.locator(
                "input[name='username'], "
                "input[name='login'], "
                "input[type='text']"
            ).first

            pass_input = page.locator(
                "input[type='password']"
            ).first

            if user_input.count() == 0 or pass_input.count() == 0:
                print("Login fields not found.")
                continue

            user_input.fill(SEREY_LOGIN)
            pass_input.fill(SEREY_PASSWORD)

            page.locator(
                "button:has-text('Login'), "
                "button:has-text('Log in'), "
                "button[type='submit']"
            ).last.click()

            page.wait_for_timeout(5000)

            if "/login" not in page.url.lower():
                print("✓ Login successful.")
                return True

        except Exception as e:
            print(f"Login attempt error: {e}")

    print("❌ Could not login to Serey.")
    return False


# ============================================================
# NETWORK CAPTURE
# ============================================================

class NetworkCapture:

    def __init__(self, page):
        self.page = page
        self.responses = []

        page.on("response", self._response)

    def _response(self, response):
        try:
            url = response.url

            # Keep likely API / post responses
            if (
                "/api/" in url.lower()
                or "graphql" in url.lower()
                or "post" in url.lower()
                or "blog" in url.lower()
                or "author" in url.lower()
            ):
                self.responses.append({
                    "url": url,
                    "status": response.status
                })

                if len(self.responses) > 500:
                    self.responses = self.responses[-500:]

        except Exception:
            pass


# ============================================================
# URL EXTRACTION
# ============================================================

def extract_urls_from_text(text):
    urls = set()

    if not text:
        return urls

    # Absolute URLs
    for match in re.findall(
        r'https?://[^\s"\'<>]+',
        text
    ):
        url = normalize_url(match.rstrip(".,);]"))

        if is_real_post_url(url):
            urls.add(url)

    # Relative author URLs
    for match in re.findall(
        r'/authors/[^"\'<>\s]+',
        text
    ):
        url = normalize_url(match.rstrip(".,);]"))

        if is_real_post_url(url):
            urls.add(url)

    return urls


def collect_urls_from_json(value, urls=None):
    if urls is None:
        urls = set()

    if isinstance(value, str):
        urls.update(extract_urls_from_text(value))
        return urls

    if isinstance(value, list):
        for item in value:
            collect_urls_from_json(item, urls)

        return urls

    if not isinstance(value, dict):
        return urls

    # Direct author + permlink / slug
    author = (
        value.get("author")
        or value.get("username")
        or value.get("user")
    )

    permlink = (
        value.get("permlink")
        or value.get("slug")
    )

    if (
        isinstance(author, str)
        and isinstance(permlink, str)
        and author.lower() == SEREY_LOGIN.lower()
    ):
        candidate = (
            f"{SEREY_BASE}/authors/"
            f"{author}/{permlink}"
        )

        if is_real_post_url(candidate):
            urls.add(candidate)

    # Search all values
    for key, item in value.items():
        if isinstance(item, str):
            urls.update(extract_urls_from_text(item))

        elif isinstance(item, (dict, list)):
            collect_urls_from_json(item, urls)

    return urls


def analyze_network_responses(capture):
    candidates = set()

    for item in capture.responses:
        url = item.get("url", "")

        # URL itself
        if is_real_post_url(url):
            candidates.add(url)

    return candidates


# ============================================================
# POST PAGE VERIFICATION
# ============================================================

def verify_real_post_page(page, url, expected_title):
    if not is_real_post_url(url):
        return False

    try:
        print(f"Verifying candidate post: {url}")

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

        if not is_real_post_url(page.url):
            return False

        expected = normalize_text(expected_title)

        if not expected:
            return True

        # Read title-like elements first
        texts = []

        try:
            title_text = page.title()
            if title_text:
                texts.append(title_text)
        except Exception:
            pass

        selectors = [
            "h1",
            "h2",
            "article h1",
            "article h2",
            "[class*='title']",
            "[class*='post-title']"
        ]

        for selector in selectors:
            try:
                loc = page.locator(selector)

                count = min(loc.count(), 10)

                for i in range(count):
                    try:
                        text = loc.nth(i).inner_text(
                            timeout=2000
                        )

                        if text:
                            texts.append(text)
                    except Exception:
                        pass

            except Exception:
                pass

        # Body as fallback
        try:
            body_text = page.locator("body").inner_text(
                timeout=5000
            )

            if body_text:
                texts.append(body_text[:30000])

        except Exception:
            pass

        normalized_texts = [
            normalize_text(x)
            for x in texts
            if x
        ]

        # Exact title
        for text in normalized_texts:
            if expected in text:
                print("✓ Post title verified.")
                return True

        # Word-based verification
        words = [
            w for w in re.findall(
                r"[a-z0-9]+",
                expected
            )
            if len(w) >= 3
        ]

        if len(words) >= 3:
            for text in normalized_texts:
                matches = sum(
                    1 for word in words
                    if word in text
                )

                ratio = matches / len(words)

                if matches >= 3 and ratio >= 0.55:
                    print(
                        f"✓ Post title partially verified "
                        f"({matches}/{len(words)} words)."
                    )
                    return True

        return False

    except Exception as e:
        print(f"Verification error: {e}")
        return False


# ============================================================
# FIND POST LINKS
# ============================================================

def find_real_post_links(page):
    links = set()

    try:
        anchors = page.locator("a[href]")
        count = min(anchors.count(), 1000)

        for i in range(count):
            try:
                href = anchors.nth(i).get_attribute("href")

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


def search_activity_for_post(page, post):
    title = normalize_text(post.get("title", ""))

    print("Searching Serey activity for the published post...")

    activity_url = (
        f"{SEREY_BASE}/authors/"
        f"{SEREY_LOGIN}/my-activity"
    )

    for attempt in range(1, 6):

        try:
            print(
                f"Activity search attempt {attempt}/5..."
            )

            page.goto(
                activity_url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(3000 + attempt * 1000)

            links = find_real_post_links(page)

            print(
                f"Found {len(links)} real post link(s)."
            )

            for url in links:

                if verify_real_post_page(
                    page,
                    url,
                    post.get("title", "")
                ):
                    return url

        except Exception as e:
            print(f"Activity search error: {e}")

        time.sleep(2)

    return None


# ============================================================
# EXPECTED URL CHECK
# ============================================================

def check_existing_post(page, post):
    """
    Important:
    If a previous publish actually succeeded but verification
    failed, this prevents publishing the same post twice.
    """

    permlink = post.get("permlink", "")

    if permlink:
        expected_url = (
            f"{SEREY_BASE}/authors/"
            f"{SEREY_LOGIN}/{permlink}"
        )

        print(
            f"Checking expected Serey URL before publishing:\n"
            f"{expected_url}"
        )

        try:
            if verify_real_post_page(
                page,
                expected_url,
                post.get("title", "")
            ):
                print(
                    "✓ This post already exists on Serey."
                )
                return expected_url

        except Exception:
            pass

    # Search activity as second protection
    try:
        existing = search_activity_for_post(
            page,
            post
        )

        if existing:
            print(
                "✓ Existing matching post found in activity."
            )
            return existing

    except Exception:
        pass

    return None


# ============================================================
# CROP MODAL
# ============================================================

def close_crop_modal(page):
    try:
        buttons = page.locator(
            "button:has-text('Confirm'), "
            "button:has-text('Done'), "
            "button:has-text('Save'), "
            "button:has-text('OK')"
        )

        if buttons.count() > 0:
            buttons.last.click(timeout=5000)
            page.wait_for_timeout(1500)
            return True

    except Exception:
        pass

    return False


def wait_for_modal_close(page, timeout=15000):
    start = time.time()

    while time.time() - start < timeout:
        try:
            modal = page.locator(
                ".ant-modal:visible, "
                "[role='dialog']:visible"
            )

            if modal.count() == 0:
                return True

        except Exception:
            return True

        time.sleep(0.5)

    return False


# ============================================================
# FIRST PUBLISH
# ============================================================

def click_first_publish(page):
    print("Attempting to click first Publish...")

    selectors = [
        "button:has-text('Publish')",
        "button:has-text('Publish Post')",
        "button:has-text('পাবলিশ')",
        "button[type='submit']"
    ]

    for selector in selectors:
        try:
            buttons = page.locator(selector)

            count = buttons.count()

            if count == 0:
                continue

            for i in range(count - 1, -1, -1):
                try:
                    btn = buttons.nth(i)

                    if not btn.is_visible():
                        continue

                    btn.scroll_into_view_if_needed()

                    btn.click(
                        timeout=10000
                    )

                    page.wait_for_timeout(2500)

                    print("✓ Publish modal opened.")
                    return True

                except Exception:
                    continue

        except Exception:
            continue

    print("❌ First Publish button not found.")
    return False


# ============================================================
# CATEGORY
# ============================================================

def select_category_in_modal(page):
    """
    Category is OPTIONAL.
    If dropdown does not work, publishing continues.
    """

    print(
        "Waiting for Publish modal and Category selector..."
    )

    try:
        modal = page.locator(
            ".ant-modal:visible"
        ).last

        if modal.count() == 0:
            modal = page.locator(
                "[role='dialog']:visible"
            ).last

        if modal.count() == 0:
            print(
                "Category modal not found. "
                "Continuing without category."
            )
            return True

        # Try select controls
        selects = modal.locator(
            ".ant-select"
        )

        if selects.count() == 0:
            print(
                "✓ Category selector not present. "
                "Continuing without category."
            )
            return True

        print("✓ Category selector found.")

        for i in range(selects.count()):
            try:
                select = selects.nth(i)

                if not select.is_visible():
                    continue

                select.click(timeout=5000)

                page.wait_for_timeout(800)

                options = page.locator(
                    ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                    ".ant-select-item-option:visible, "
                    "[role='option']:visible"
                )

                if options.count() > 0:
                    print(
                        f"✓ Category option(s) found: "
                        f"{options.count()}"
                    )

                    # Choose first real option
                    for j in range(options.count()):
                        try:
                            option = options.nth(j)

                            text = normalize_text(
                                option.inner_text()
                            )

                            if text and text not in [
                                "select",
                                "category",
                                "choose category"
                            ]:
                                option.click(
                                    timeout=5000
                                )

                                page.wait_for_timeout(500)
                                print("✓ Category selected.")
                                return True

                        except Exception:
                            continue

                # Close dropdown by Escape
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

            except Exception:
                continue

    except Exception as e:
        print(
            f"Category handling skipped: {e}"
        )

    print(
        "⚠ Category could not be selected. "
        "Continuing to final Publish."
    )

    return True


# ============================================================
# FINAL PUBLISH
# ============================================================

def get_visible_publish_button(page):
    selectors = [
        ".ant-modal:visible button:has-text('Publish')",
        ".ant-modal:visible button[type='submit']",
        "[role='dialog']:visible button:has-text('Publish')",
        "[role='dialog']:visible button[type='submit']",
    ]

    for selector in selectors:
        try:
            buttons = page.locator(selector)

            count = buttons.count()

            for i in range(count - 1, -1, -1):
                btn = buttons.nth(i)

                try:
                    if btn.is_visible():
                        return btn
                except Exception:
                    continue

        except Exception:
            continue

    return None


def click_final_publish(page):
    print("Searching for final Publish button...")

    btn = get_visible_publish_button(page)

    if btn is None:
        print(
            "❌ Final Publish button could not be found."
        )
        return False

    try:
        btn.scroll_into_view_if_needed()

        # Wait for enabled state
        start = time.time()

        while time.time() - start < 20:

            try:
                disabled = btn.is_disabled()

                if not disabled:
                    break

            except Exception:
                pass

            page.wait_for_timeout(500)

        try:
            if btn.is_disabled():
                print(
                    "⚠ Final Publish button is still disabled."
                )
        except Exception:
            pass

        # IMPORTANT:
        # Only ONE real click.
        # No JavaScript click + Playwright click.
        btn.click(
            timeout=15000
        )

        print(
            "✓ Final Publish button clicked once."
        )

        page.wait_for_timeout(3000)

        return True

    except Exception as e:
        print(
            f"❌ Final Publish click failed: {e}"
        )
        return False


# ============================================================
# DEBUG
# ============================================================

def save_debug(page):
    filename = (
        f"serey_debug_"
        f"{int(time.time())}.html"
    )

    try:
        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(page.content())

        print(
            f"✓ Debug HTML saved: {filename}"
        )

    except Exception as e:
        print(
            f"Could not save debug HTML: {e}"
        )

    try:
        screenshot = (
            f"serey_debug_"
            f"{int(time.time())}.png"
        )

        page.screenshot(
            path=screenshot,
            full_page=True
        )

        print(
            f"✓ Debug screenshot saved: {screenshot}"
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
    # IMPORTANT DUPLICATE PROTECTION
    # --------------------------------------------------------

    existing = check_existing_post(
        page,
        post
    )

    if existing:
        print(
            "✓ Publish skipped because matching Serey "
            "post already exists."
        )

        return existing

    # --------------------------------------------------------
    # Open new post
    # --------------------------------------------------------

    try:
        page.goto(
            SEREY_NEW_POST,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

    except Exception as e:
        print(
            f"❌ Could not open new post page: {e}"
        )
        return None

    remove_overlays(page)

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    try:
        title_input = page.locator(
            "input[name='title'], "
            "input[placeholder*='Title' i], "
            "textarea[placeholder*='Title' i]"
        ).first

        if title_input.count() == 0:
            print("❌ Title input not found.")
            return None

        title_input.fill(
            post["title"]
        )

        print("✓ Title filled")

    except Exception as e:
        print(
            f"❌ Title fill failed: {e}"
        )
        return None

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    try:
        body = post.get("body", "")

        # Try ProseMirror / contenteditable
        body_editor = page.locator(
            "[contenteditable='true']"
        ).first

        if body_editor.count() == 0:
            body_editor = page.locator(
                "textarea"
            ).last

        if body_editor.count() == 0:
            print("❌ Body editor not found.")
            return None

        body_editor.click()

        # For contenteditable
        try:
            body_editor.fill(body)
        except Exception:
            page.keyboard.insert_text(body)

        print(
            f"✓ Body filled ({len(body)} characters)"
        )

    except Exception as e:
        print(
            f"❌ Body fill failed: {e}"
        )
        return None

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image_file = None

    try:
        if post.get("thumbnail"):

            image_file = download_image(
                post["thumbnail"]
            )

            if image_file:

                # Search file inputs
                file_inputs = page.locator(
                    "input[type='file']"
                )

                if file_inputs.count() > 0:

                    uploaded = False

                    for i in range(file_inputs.count()):
                        try:
                            inp = file_inputs.nth(i)

                            inp.set_input_files(
                                image_file
                            )

                            page.wait_for_timeout(2500)

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
                            "could not be completed."
                        )

                else:
                    print(
                        "⚠ No file input found."
                    )

    except Exception as e:
        print(
            f"⚠ Image upload error: {e}"
        )

    # --------------------------------------------------------
    # CROP
    # --------------------------------------------------------

    try:
        page.wait_for_timeout(2000)

        if close_crop_modal(page):
            print(
                "✓ Thumbnail processing finished."
            )
        else:
            print(
                "✓ No crop confirmation required."
            )

    except Exception:
        pass

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    if not click_first_publish(page):
        save_debug(page)
        return None

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    select_category_in_modal(page)

    page.wait_for_timeout(1000)

    # --------------------------------------------------------
    # FINAL PUBLISH
    # --------------------------------------------------------

    if not click_final_publish(page):
        save_debug(page)
        return None

    # --------------------------------------------------------
    # VERIFICATION
    # --------------------------------------------------------

    print(
        "Waiting for Serey to create the post..."
    )

    expected_url = None

    if post.get("permlink"):
        expected_url = (
            f"{SEREY_BASE}/authors/"
            f"{SEREY_LOGIN}/{post['permlink']}"
        )

    # Poll several times
    checkpoints = [
        3,
        7,
        12,
        20,
        30,
        45,
        60
    ]

    for wait_seconds in checkpoints:

        time.sleep(
            3 if wait_seconds <= 3
            else 4
        )

        # ----------------------------------------------------
        # Current URL
        # ----------------------------------------------------

        try:
            current_url = page.url

            if is_real_post_url(current_url):

                if verify_real_post_page(
                    page,
                    current_url,
                    post["title"]
                ):
                    print(
                        f"✓ PUBLISH VERIFIED:\n"
                        f"{current_url}"
                    )
                    return current_url

        except Exception:
            pass

        # ----------------------------------------------------
        # Network candidates
        # ----------------------------------------------------

        candidates = analyze_network_responses(
            capture
        )

        for candidate in candidates:

            try:
                if verify_real_post_page(
                    page,
                    candidate,
                    post["title"]
                ):
                    print(
                        f"✓ PUBLISH VERIFIED:\n"
                        f"{candidate}"
                    )
                    return candidate

            except Exception:
                continue

        # ----------------------------------------------------
        # Expected permlink URL
        # ----------------------------------------------------

        if expected_url:

            try:
                if verify_real_post_page(
                    page,
                    expected_url,
                    post["title"]
                ):
                    print(
                        f"✓ PUBLISH VERIFIED:\n"
                        f"{expected_url}"
                    )
                    return expected_url

            except Exception:
                pass

        # ----------------------------------------------------
        # Activity search
        # ----------------------------------------------------

        if wait_seconds in [12, 30, 60]:

            try:
                found = search_activity_for_post(
                    page,
                    post
                )

                if found:
                    print(
                        f"✓ PUBLISH VERIFIED:\n"
                        f"{found}"
                    )
                    return found

            except Exception:
                pass

        print(
            f"Still waiting for verification "
            f"({wait_seconds}s)..."
        )

    # --------------------------------------------------------
    # FINAL DUPLICATE CHECK
    # --------------------------------------------------------

    try:
        print(
            "Performing final duplicate check..."
        )

        found = search_activity_for_post(
            page,
            post
        )

        if found:
            print(
                f"✓ PUBLISH VERIFIED:\n"
                f"{found}"
            )
            return found

    except Exception:
        pass

    print(
        "❌ PUBLISH COULD NOT BE VERIFIED"
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

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}"
    )

    posts = get_posts()

    unsynced = [
        p for p in posts
        if p["identifier"] not in synced
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

    selected = unsynced[:POSTS_PER_RUN]

    for post in selected:

        print(
            f"Selected: "
            f"{post['identifier']}"
        )

        print(
            f"Created: "
            f"{post['created']}"
        )

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
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        # Attach network capture BEFORE login/publishing
        capture = NetworkCapture(page)

        try:

            if not login(page):
                print(
                    "❌ Login failed."
                )
                return

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
                        f"✓ Added to synced_posts.json:"
                        f" {post['identifier']}"
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


if __name__ == "__main__":
    main()
