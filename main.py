import os
import json
import re
import time
import html
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# STEEM -> BENGALI SEREY AUTO SYNC
# LAST 365 DAYS -> OLDEST TO NEWEST
# ONE POST PER RUN
# ============================================================

STEEM_USERNAME = os.getenv("STEEM_USERNAME", "").strip()
SEREY_LOGIN = os.getenv("SEREY_LOGIN", "").strip()
SEREY_PASSWORD = os.getenv("SEREY_PASSWORD", "").strip()

POSTS_PER_RUN = 1
DAYS_LIMIT = 365

SEREY_BASE = "https://bengali.serey.io"
SEREY_LOGIN_URL = f"{SEREY_BASE}/login"
SEREY_NEW_POST_URL = f"{SEREY_BASE}/blog/post/new"

STATE_FILE = "synced_posts.json"

RPC_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]

REQUEST_TIMEOUT = 12
BROWSER_TIMEOUT = 15000


# ============================================================
# LOGGING
# ============================================================

def log(message):
    print(message, flush=True)


# ============================================================
# BASIC CHECK
# ============================================================

def check_environment():
    log("")
    log("=" * 60)
    log("STEEM -> BENGALI SEREY AUTO SYNC")
    log("LAST 365 DAYS -> OLDEST TO NEWEST")
    log("=" * 60)

    if not STEEM_USERNAME:
        raise RuntimeError("STEEM_USERNAME secret is missing.")

    if not SEREY_LOGIN:
        raise RuntimeError("SEREY_LOGIN secret is missing.")

    if not SEREY_PASSWORD:
        raise RuntimeError("SEREY_PASSWORD secret is missing.")

    log(f"✓ Steem username: @{STEEM_USERNAME}")
    log(f"✓ Serey login: {SEREY_LOGIN}")
    log("✓ Required secrets found.")


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        log("✓ No previous sync state found.")
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            result = set(str(x) for x in data)
        elif isinstance(data, dict):
            result = set(str(x) for x in data.keys())
        else:
            result = set()

        log(f"✓ Previously synced: {len(result)}")
        return result

    except Exception as e:
        log(f"⚠ Could not read {STATE_FILE}: {e}")
        return set()


def save_state(state):
    data = sorted(state)

    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(temp_file, STATE_FILE)

    log(f"✓ Sync state saved. Total synced: {len(state)}")


# ============================================================
# STEEM RPC
# ============================================================

def rpc_call(session, rpc_url, method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        response = session.post(
            rpc_url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "steemit-to-serey-sync/1.0",
            },
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            raise RuntimeError(str(data["error"]))

        return data.get("result")

    except Exception as e:
        raise RuntimeError(f"{rpc_url} -> {e}")


def get_steem_posts():
    log("")
    log("[1/8] Connecting to Steem RPC...")

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_LIMIT)

    log(f"✓ Cutoff date: {cutoff.isoformat()}")
    log(f"✓ Checking account: @{STEEM_USERNAME}")

    session = requests.Session()

    # We collect posts by using get_discussions_by_blog.
    # Multiple pages are requested until we reach the cutoff.
    all_posts = []
    start_author = STEEM_USERNAME
    start_permlink = ""

    max_pages = 150

    for page_number in range(1, max_pages + 1):

        log(f"  RPC page {page_number}...")

        result = None
        successful_rpc = None

        for rpc in RPC_NODES:
            try:
                result = rpc_call(
                    session,
                    rpc,
                    "condenser_api.get_discussions_by_blog",
                    [{
                        "tag": STEEM_USERNAME,
                        "limit": 100,
                        "start_author": start_author,
                        "start_permlink": start_permlink,
                    }],
                )

                successful_rpc = rpc
                log(f"  ✓ RPC success: {rpc}")
                break

            except Exception as e:
                log(f"  ⚠ RPC failed: {e}")

        if result is None:
            raise RuntimeError("All Steem RPC nodes failed.")

        if not result:
            log("  ✓ No more posts returned.")
            break

        reached_cutoff = False

        for post in result:

            author = post.get("author", "")
            permlink = post.get("permlink", "")

            if author != STEEM_USERNAME:
                continue

            created_text = post.get("created")

            if not created_text:
                continue

            try:
                created = datetime.fromisoformat(
                    created_text.replace("Z", "+00:00")
                )
            except Exception:
                continue

            if created < cutoff:
                reached_cutoff = True
                continue

            post["_created_dt"] = created
            all_posts.append(post)

        last = result[-1]

        last_author = last.get("author", "")
        last_permlink = last.get("permlink", "")

        if reached_cutoff:
            break

        if last_author == start_author and last_permlink == start_permlink:
            break

        start_author = last_author
        start_permlink = last_permlink

        time.sleep(0.2)

    # Remove duplicates
    unique = {}

    for post in all_posts:
        key = f"{post.get('author')}/{post.get('permlink')}"
        unique[key] = post

    posts = list(unique.values())

    # Oldest first
    posts.sort(key=lambda x: x["_created_dt"])

    log("")
    log(f"✓ Collected posts in last {DAYS_LIMIT} days: {len(posts)}")

    return posts


# ============================================================
# POST DATA
# ============================================================

def post_key(post):
    return f"{post.get('author')}/{post.get('permlink')}"


def get_post_url(post):
    return (
        "https://steemit.com/"
        + post.get("category", "")
        + "/@"
        + post.get("author", "")
        + "/"
        + post.get("permlink", "")
    )


def clean_body(body):
    if not body:
        return ""

    text = body

    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    # Remove images
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

    # Remove HTML image tags
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)

    # Remove iframe
    text = re.sub(r"<iframe.*?</iframe>", "", text, flags=re.I | re.S)

    # Convert common HTML breaks
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)

    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode entities
    text = html.unescape(text)

    # Remove excessive blank lines
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)

    return text.strip()


def get_thumbnail(post):
    """
    Try to get the first image from the original Steem body.
    """
    body = post.get("body", "") or ""

    patterns = [
        r'!\[[^\]]*\]\((https?://[^)\s]+)',
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'(https?://[^\s"\']+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^\s"\']*)?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, body, flags=re.I)

        if match:
            url = match.group(1)

            if url.startswith("http"):
                return url

    return None


def build_serey_body(post):
    body = clean_body(post.get("body", ""))

    original_url = get_post_url(post)

    footer = (
        "\n\n---\n\n"
        f"Original post: {original_url}"
    )

    return body + footer


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_thumbnail(image_url):
    if not image_url:
        log("✓ No thumbnail image found.")
        return None

    log(f"✓ Thumbnail URL found:")
    log(f"  {image_url}")

    try:
        response = requests.get(
            image_url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0",
            },
        )

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        if "image" not in content_type:
            log("⚠ URL did not return an image.")
            return None

        extension = ".jpg"

        if "png" in content_type:
            extension = ".png"
        elif "webp" in content_type:
            extension = ".webp"
        elif "gif" in content_type:
            extension = ".gif"
        elif "jpeg" in content_type:
            extension = ".jpg"

        filename = f"thumbnail_{int(time.time())}{extension}"

        with open(filename, "wb") as f:
            f.write(response.content)

        size_mb = len(response.content) / (1024 * 1024)

        log(f"✓ Thumbnail downloaded: {filename}")
        log(f"✓ Thumbnail size: {size_mb:.2f} MB")

        return filename

    except Exception as e:
        log(f"⚠ Thumbnail download failed: {e}")
        return None


# ============================================================
# BROWSER HELPERS
# ============================================================

def visible(locator):
    try:
        return locator.is_visible()
    except Exception:
        return False


def safe_text(locator):
    try:
        return locator.inner_text(timeout=2000)
    except Exception:
        return ""


# ============================================================
# SEREY LOGIN
# ============================================================

def login(page):
    log("")
    log("[3/8] Opening Serey...")

    try:
        page.goto(
            SEREY_NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=BROWSER_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠ Initial Serey page load warning: {e}")

    log(f"✓ Current URL: {page.url}")

    # If already logged in
    if "/login" not in page.url.lower():
        log("✓ Existing Serey session detected.")
        return True

    log("✓ Login page detected.")

    # Username / email / login input
    username_selectors = [
        'input[name="username"]',
        'input[name="email"]',
        'input[type="email"]',
        'input[placeholder*="email" i]',
        'input[placeholder*="username" i]',
        'input[type="text"]',
    ]

    password_selectors = [
        'input[name="password"]',
        'input[type="password"]',
    ]

    username_input = None
    password_input = None

    for selector in username_selectors:
        try:
            loc = page.locator(selector).first
            if visible(loc):
                username_input = loc
                break
        except Exception:
            pass

    for selector in password_selectors:
        try:
            loc = page.locator(selector).first
            if visible(loc):
                password_input = loc
                break
        except Exception:
            pass

    if username_input is None:
        raise RuntimeError("Could not find Serey username/login field.")

    if password_input is None:
        raise RuntimeError("Could not find Serey password field.")

    username_input.fill(SEREY_LOGIN)
    password_input.fill(SEREY_PASSWORD)

    log("✓ Login credentials filled.")

    # Find login button
    buttons = page.locator("button")

    clicked = False

    for i in range(min(buttons.count(), 30)):
        try:
            btn = buttons.nth(i)

            if not visible(btn):
                continue

            text = safe_text(btn).strip().lower()

            if any(x in text for x in ["login", "log in", "sign in"]):
                btn.click(timeout=5000)
                clicked = True
                break

        except Exception:
            continue

    if not clicked:
        raise RuntimeError("Could not find Login button.")

    log("✓ Login button clicked.")

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=10000,
        )
    except Exception:
        pass

    time.sleep(2)

    log(f"✓ After login URL: {page.url}")

    if "/login" in page.url.lower():
        raise RuntimeError("Serey login failed.")

    log("✓ Serey login successful.")
    return True


# ============================================================
# EXISTING POST CHECK
# ============================================================

def expected_serey_url(post):
    return (
        f"{SEREY_BASE}/authors/"
        f"{SEREY_LOGIN}/"
        f"{post.get('permlink')}"
    )


def check_existing_post(page, post):
    """
    Short timeout only.
    This prevents the workflow from hanging for a long time.
    """

    url = expected_serey_url(post)

    log("")
    log("[4/8] Checking duplicate post...")
    log(f"  Expected URL: {url}")

    try:
        response = page.request.get(
            url,
            timeout=8000,
        )

        status = response.status

        log(f"  HTTP status: {status}")

        if status == 200:
            text = response.text().lower()

            # If page contains the permlink/title, treat as existing.
            title = (post.get("title") or "").lower()

            if (
                post.get("permlink", "").lower() in text
                or (title and title[:40] in text)
            ):
                log("⚠ This post appears to already exist on Serey.")
                return True

        log("✓ Existing post not confirmed.")
        return False

    except Exception as e:
        log(f"✓ Duplicate check skipped due to timeout/error: {e}")
        return False


# ============================================================
# OPEN NEW POST
# ============================================================

def open_new_post(page):
    log("")
    log("[5/8] Opening Serey New Post page...")

    page.goto(
        SEREY_NEW_POST_URL,
        wait_until="domcontentloaded",
        timeout=BROWSER_TIMEOUT,
    )

    time.sleep(1)

    log(f"✓ New post page: {page.url}")

    if "/login" in page.url.lower():
        raise RuntimeError("Serey session expired.")

    return True


# ============================================================
# FILL TITLE / BODY
# ============================================================

def fill_title(page, title):
    selectors = [
        'input[name="title"]',
        'input[placeholder*="title" i]',
        'textarea[placeholder*="title" i]',
        'input[type="text"]',
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first

            if visible(loc):
                loc.fill(title)
                log("✓ Title filled.")
                return True

        except Exception:
            pass

    raise RuntimeError("Could not find title field.")


def fill_body(page, body):
    # Textarea first
    selectors = [
        'textarea[name="body"]',
        'textarea[placeholder*="content" i]',
        'textarea[placeholder*="body" i]',
        'textarea',
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first

            if visible(loc):
                loc.fill(body)
                log("✓ Body filled using textarea.")
                return True

        except Exception:
            pass

    # Contenteditable
    editables = page.locator('[contenteditable="true"]')

    for i in range(min(editables.count(), 20)):
        try:
            loc = editables.nth(i)

            if visible(loc):
                loc.click()
                loc.fill(body)
                log("✓ Body filled using contenteditable.")
                return True

        except Exception:
            pass

    raise RuntimeError("Could not find Serey body editor.")


# ============================================================
# UPLOAD THUMBNAIL
# ============================================================

def upload_thumbnail(page, filename):
    if not filename:
        log("✓ No thumbnail to upload.")
        return

    log("✓ Looking for thumbnail/file input...")

    inputs = page.locator('input[type="file"]')

    count = inputs.count()

    if count == 0:
        log("⚠ No file input found. Continuing without thumbnail.")
        return

    for i in range(count):
        try:
            loc = inputs.nth(i)

            if visible(loc) or True:
                loc.set_input_files(filename)
                log("✓ Thumbnail uploaded.")
                time.sleep(1)
                return

        except Exception as e:
            log(f"⚠ File input {i} failed: {e}")

    log("⚠ Thumbnail upload failed. Continuing.")


# ============================================================
# CLICK FIRST PUBLISH
# ============================================================

def click_first_publish(page):
    log("")
    log("[6/8] Looking for first Publish button...")

    # Do NOT touch category.
    # Do NOT use JS click.

    buttons = page.locator("button")

    candidates = []

    for i in range(min(buttons.count(), 100)):
        try:
            btn = buttons.nth(i)

            if not visible(btn):
                continue

            text = safe_text(btn).strip()

            if text.lower() == "publish":
                candidates.append(btn)

        except Exception:
            continue

    if not candidates:
        # fallback: buttons containing Publish
        for i in range(min(buttons.count(), 100)):
            try:
                btn = buttons.nth(i)

                if not visible(btn):
                    continue

                text = safe_text(btn).strip().lower()

                if "publish" in text:
                    candidates.append(btn)

            except Exception:
                continue

    if not candidates:
        raise RuntimeError("First Publish button not found.")

    log(f"✓ Publish button candidates: {len(candidates)}")

    candidates[-1].click(timeout=5000)

    log("✓ First Publish button clicked.")

    time.sleep(1)

    return True


# ============================================================
# FINAL PUBLISH MODAL
# ============================================================

def click_final_publish(page):
    log("")
    log("[7/8] Looking for final Publish confirmation...")

    # Give modal a short time to appear.
    for attempt in range(1, 7):

        log(f"  Modal check {attempt}/6...")

        # Prefer visible dialogs/modals
        containers = [
            page.locator('[role="dialog"]'),
            page.locator(".ant-modal"),
            page.locator(".modal"),
            page.locator('[class*="modal" i]'),
        ]

        for container in containers:

            try:
                count = container.count()

                for i in range(count):
                    box = container.nth(i)

                    if not visible(box):
                        continue

                    buttons = box.locator("button")

                    for j in range(buttons.count()):
                        try:
                            btn = buttons.nth(j)

                            if not visible(btn):
                                continue

                            text = safe_text(btn).strip().lower()

                            if text == "publish" or (
                                "publish" in text
                                and "cancel" not in text
                            ):
                                btn.click(timeout=5000)

                                log("✓ Final Publish button clicked once.")
                                return True

                        except Exception:
                            continue

            except Exception:
                continue

        time.sleep(1)

    # Final fallback: visible button outside modal
    buttons = page.locator("button")

    for i in range(min(buttons.count(), 100)):
        try:
            btn = buttons.nth(i)

            if not visible(btn):
                continue

            text = safe_text(btn).strip().lower()

            if text == "publish":
                btn.click(timeout=5000)

                log("✓ Final Publish button clicked.")
                return True

        except Exception:
            continue

    raise RuntimeError("Final Publish button could not be found.")


# ============================================================
# VERIFY
# ============================================================

def verify_post(page, post):
    log("")
    log("[8/8] Verifying Serey post...")

    url = expected_serey_url(post)

    log(f"✓ Expected post URL:")
    log(f"  {url}")

    # Do not use a 20-second navigation timeout.
    # Check several times with short requests.

    for attempt in range(1, 9):

        log(f"  Verification {attempt}/8...")

        try:
            response = page.request.get(
                url,
                timeout=8000,
            )

            status = response.status

            if status == 200:
                text = response.text()

                title = post.get("title", "")

                if (
                    post.get("permlink", "") in text
                    or title[:50].lower() in text.lower()
                ):
                    log("✓ Serey post verified!")
                    log(f"✓ POST URL: {url}")
                    return True

                log("  Page exists, but post content not confirmed.")

            else:
                log(f"  HTTP {status}")

        except Exception as e:
            log(f"  Verification error: {e}")

        time.sleep(3)

    log("⚠ Post could not be verified automatically.")

    return False


# ============================================================
# DEBUG
# ============================================================

def save_debug(page):
    timestamp = int(time.time())

    html_file = f"serey_debug_{timestamp}.html"
    png_file = f"serey_debug_{timestamp}.png"

    try:
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(page.content())

        log(f"✓ Debug HTML saved: {html_file}")
    except Exception as e:
        log(f"⚠ Debug HTML failed: {e}")

    try:
        page.screenshot(
            path=png_file,
            full_page=True,
        )

        log(f"✓ Debug screenshot saved: {png_file}")
    except Exception as e:
        log(f"⚠ Debug screenshot failed: {e}")


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    check_environment()

    synced = load_state()

    log("")
    log("[2/8] Collecting Steem posts...")

    posts = get_steem_posts()

    unsynced = [
        post
        for post in posts
        if post_key(post) not in synced
    ]

    log(f"✓ Unsynced posts: {len(unsynced)}")

    if not unsynced:
        log("")
        log("✓ Nothing new to sync.")
        return

    selected = unsynced[:POSTS_PER_RUN]

    log("")
    log("Selected post(s):")

    for post in selected:
        log(
            f"  {post.get('author')}/"
            f"{post.get('permlink')}"
        )

    post = selected[0]

    log("")
    log("=" * 60)
    log("PROCESSING POST")
    log("=" * 60)

    log(f"Title: {post.get('title')}")
    log(f"Created: {post.get('created')}")
    log(f"Permlink: {post.get('permlink')}")

    thumbnail_url = get_thumbnail(post)

    thumbnail_file = download_thumbnail(thumbnail_url)

    body = build_serey_body(post)

    with sync_playwright() as p:

        browser = None
        page = None

        try:

            log("")
            log("Launching Chromium...")

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = browser.new_context(
                viewport={
                    "width": 1366,
                    "height": 900,
                },
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )

            page = context.new_page()

            page.set_default_timeout(BROWSER_TIMEOUT)

            log("✓ Chromium started.")

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            login(page)

            # ------------------------------------------------
            # DUPLICATE CHECK
            # ------------------------------------------------

            if check_existing_post(page, post):
                log("")
                log("⚠ Post already exists on Serey.")
                log("✓ Marking as synced to avoid duplicate.")
                synced.add(post_key(post))
                save_state(synced)
                return

            # ------------------------------------------------
            # NEW POST
            # ------------------------------------------------

            open_new_post(page)

            # ------------------------------------------------
            # FILL
            # ------------------------------------------------

            log("")
            log("Filling Serey post form...")

            fill_title(
                page,
                post.get("title", "").strip(),
            )

            fill_body(
                page,
                body,
            )

            # ------------------------------------------------
            # THUMBNAIL
            # ------------------------------------------------

            upload_thumbnail(
                page,
                thumbnail_file,
            )

            # ------------------------------------------------
            # PUBLISH
            # ------------------------------------------------

            click_first_publish(page)

            click_final_publish(page)

            # ------------------------------------------------
            # VERIFY
            # ------------------------------------------------

            verified = verify_post(
                page,
                post,
            )

            if verified:

                synced.add(post_key(post))
                save_state(synced)

                log("")
                log("=" * 60)
                log("✓ SUCCESS")
                log("=" * 60)
                log(f"✓ Synced: {post_key(post)}")
                log(f"✓ Serey URL: {expected_serey_url(post)}")

            else:

                log("")
                log("=" * 60)
                log("⚠ PUBLISH MAY HAVE SUCCEEDED,")
                log("BUT AUTOMATIC VERIFICATION FAILED.")
                log("=" * 60)

                log(
                    f"Expected URL: "
                    f"{expected_serey_url(post)}"
                )

                log(
                    "Post was NOT added to synced_posts.json "
                    "because verification failed."
                )

                save_debug(page)

                raise RuntimeError(
                    "Serey publish could not be verified."
                )

        except Exception as e:

            log("")
            log("=" * 60)
            log("❌ FAILED")
            log("=" * 60)
            log(f"Error: {e}")

            if page is not None:
                save_debug(page)

            raise

        finally:

            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    # Remove downloaded thumbnail
    if thumbnail_file and os.path.exists(thumbnail_file):
        try:
            os.remove(thumbnail_file)
        except Exception:
            pass

    elapsed = time.time() - start_time

    log("")
    log(f"✓ Total runtime: {elapsed:.1f} seconds")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("")
        log("❌ Cancelled.")
        raise
    except Exception as e:
        log("")
        log(f"❌ WORKFLOW FAILED: {e}")
        raise
