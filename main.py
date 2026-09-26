import os
import json
import re
import time
import mimetypes
from datetime import datetime, timedelta, timezone

import requests
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ.get("STEEM_USERNAME", "").strip()

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"

POSTS_PER_RUN = 1
DAYS_LIMIT = 365

TEMP_IMAGE_PREFIX = "temp_image"

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]


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

    for node in STEEM_NODES:
        try:
            r = requests.post(
                node,
                json=payload,
                timeout=20
            )

            r.raise_for_status()

            data = r.json()

            if "error" in data:
                raise Exception(data["error"])

            print(f"✓ RPC success: {node}", flush=True)

            return data["result"]

        except Exception as e:
            print(
                f"RPC {node} failed: {e}",
                flush=True
            )

    raise Exception("All Steem RPC nodes failed")


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

        return set()

    except Exception as e:

        print(
            f"⚠ Could not read {SYNC_FILE}: {e}",
            flush=True
        )

        return set()


def save_synced(data):

    temp_file = SYNC_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(data),
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp_file,
        SYNC_FILE
    )


# ============================================================
# THUMBNAIL + CLEAN BODY
# ============================================================

def extract_thumbnail_and_body(body, metadata):

    thumbnail = None

    try:
        meta = json.loads(metadata or "{}")
        images = meta.get("image", [])
        if isinstance(images, list):
            for x in images:
                if isinstance(x, str) and x.startswith("http"):
                    thumbnail = x
                    break
    except Exception:
        pass

    if not thumbnail:
        m = re.search(r'!\[[^\]]*\]\((https?://[^)\s]+)', body, re.I)
        if m:
            thumbnail = m.group(1)

    if not thumbnail:
        m = re.search(r'<img[^>]+src=["\'](https?://[^"\'>\s]+)', body, re.I)
        if m:
            thumbnail = m.group(1)

    if not thumbnail:
        m = re.search(r'(https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?)', body, re.I)
        if m:
            thumbnail = m.group(1)

    # Clean body
    body = re.sub(r'!\[[^\]]*\]\(\s*https?://[^)\s]+\s*\)', '', body, flags=re.I)
    body = re.sub(r'<img\b[^>]*>', '', body, flags=re.I)
    body = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?', '', body, flags=re.I)
    body = re.sub(r'<[^>]+>', '', body)
    body = re.sub(r'^\s{0,3}#{1,6}\s*', '', body, flags=re.M)
    body = re.sub(r'\*\*(.*?)\*\*', r'\1', body, flags=re.S)
    body = re.sub(r'(?<!\*)\*(.*?)\*(?!\*)', r'\1', body, flags=re.S)
    body = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1', body, flags=re.I)

    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.fullmatch(r'https?://\S+', stripped, re.I):
            continue
        lines.append(line)

    body = "\n".join(lines)
    body = re.sub(r'\n[ \t]*\n[ \t]*\n+', '\n\n', body)
    body = "\n".join(line.strip() for line in body.splitlines())

    return body.strip(), thumbnail


# ============================================================
# STEEM DATE
# ============================================================

def parse_steem_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():
    print(f"Collecting posts from @{STEEM_USERNAME} for the last {DAYS_LIMIT} days...", flush=True)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=DAYS_LIMIT)
    print(f"Post cut-off date: {cutoff_date.strftime('%Y-%m-%d')}", flush=True)

    posts = []
    seen = set()
    start_author = None
    start_permlink = None
    reached_old = False

    while len(posts) < 5000 and not reached_old:
        params = {"tag": STEEM_USERNAME, "limit": 100}
        if start_author:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        result = rpc("condenser_api.get_discussions_by_blog", params)
        if not result:
            break

        batch = result[1:] if start_author else result
        if not batch:
            break

        for p in batch:
            if p.get("author") != STEEM_USERNAME:
                continue

            author = p.get("author", "")
            permlink = p.get("permlink", "")
            if not permlink:
                continue

            post_id = f"{author}/{permlink}"
            if post_id in seen:
                continue

            created_str = p.get("created", "")
            created_dt = parse_steem_date(created_str)

            if created_dt and created_dt < cutoff_date:
                reached_old = True
                break

            seen.add(post_id)
            body, thumbnail = extract_thumbnail_and_body(
                p.get("body", ""),
                p.get("json_metadata", "{}")
            )

            posts.append({
                "id": post_id,
                "title": p.get("title", "").strip(),
                "body": body,
                "thumbnail": thumbnail,
                "created": created_str,
                "category": p.get("category", "")
            })

        last = result[-1]
        new_author = last.get("author")
        new_permlink = last.get("permlink")

        if new_author == start_author and new_permlink == start_permlink:
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100 or reached_old:
            break

        time.sleep(0.3)

    posts.reverse()
    print(f"Total posts collected from the last {DAYS_LIMIT} days: {len(posts)}", flush=True)
    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):
    if not url:
        return None

    try:
        print(f"Downloading cover thumbnail: {url}", flush=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://steemit.com/"
        }
        r = requests.get(url, timeout=25, headers=headers)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "").lower()
        ext = mimetypes.guess_extension(content_type.split(";")[0]) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"

        file_path = f"{TEMP_IMAGE_PREFIX}{ext}"
        with open(file_path, "wb") as f:
            f.write(r.content)

        print(f"✓ Cover image saved: {file_path} ({len(r.content)} bytes)", flush=True)
        return file_path
    except Exception as e:
        print(f"❌ Cover image download failed: {e}", flush=True)
        return None


# ============================================================
# DISMISS COOKIE & POPUP OVERLAYS
# ============================================================

def dismiss_overlays(page):
    """কুকি নোটিশ বা স্ক্রিনের সামনের কোনো ওভারলে বন্ধ/রিমুভ করে দেয়"""
    try:
        page.evaluate("""
            () => {
                // ১. কুকি বা ওভারলে ব্যানার রিমুভ করা
                const overlays = document.querySelectorAll(
                    '[class*="cookie"], [id*="cookie"], .no-cookie-notice-overlay, ' +
                    '[class*="notice-overlay"], [class*="consent"]'
                );
                overlays.forEach(el => el.remove());

                // ২. যদি কোনো বাটনে Accept/Got it থাকে তবে ক্লিক করা
                const buttons = Array.from(document.querySelectorAll('button, a'));
                buttons.forEach(btn => {
                    const txt = (btn.innerText || '').toLowerCase().trim();
                    if (txt.includes('accept') || txt.includes('got it') || txt.includes('agree') || txt.includes('স্মরণ রাখুন')) {
                        btn.click();
                    }
                });
            }
        """)
        page.wait_for_timeout(500)
    except Exception:
        pass


# ============================================================
# LOGIN
# ============================================================

def login(page):
    print("Logging into Serey...", flush=True)

    page.goto(SEREY, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    dismiss_overlays(page)

    print(f"Initial page URL: {page.url}", flush=True)

    logged_in_indicators = page.locator(
        f'a[href*="/authors/{SEREY_LOGIN}"], '
        'button:has-text("Logout"), a:has-text("Logout"), '
        'button:has-text("লগআউট"), a:has-text("লগআউট"), '
        '.ant-avatar, img[alt*="avatar"]'
    )

    if logged_in_indicators.count() > 0 and logged_in_indicators.first.is_visible():
        print("✓ Already logged in Serey.", flush=True)
        return

    login_buttons = page.locator(
        'button:has-text("Log in"), a:has-text("Log in"), '
        'button:has-text("Log In"), a:has-text("Log In"), '
        'button:has-text("লগইন"), a:has-text("লগইন"), '
        'a[href*="/login"], button[class*="login"]'
    )

    if login_buttons.count() > 0:
        for idx in range(login_buttons.count()):
            btn = login_buttons.nth(idx)
            try:
                if btn.is_visible():
                    print(f"Clicking login button #{idx + 1}...", flush=True)
                    btn.click(timeout=10000)
                    page.wait_for_timeout(3000)
                    break
            except Exception as e:
                print(f"Click attempt note: {e}", flush=True)

    user_in = page.locator(
        'input[id="username"], '
        'input[name="username"], '
        'input[placeholder*="Username" i], '
        'input[placeholder*="ব্যবহারকারী" i], '
        '.ant-modal input[type="text"], '
        'input[type="text"]'
    ).first

    pass_in = page.locator(
        'input[id="password"], '
        'input[name="password"], '
        'input[placeholder*="Private Key" i], '
        'input[placeholder*="Password" i], '
        '.ant-modal input[type="password"], '
        'input[type="password"]'
    ).first

    try:
        user_in.wait_for(state="visible", timeout=25000)
        pass_in.wait_for(state="visible", timeout=25000)

        user_in.fill(SEREY_LOGIN)
        page.wait_for_timeout(500)

        pass_in.fill(SEREY_PASSWORD)
        page.wait_for_timeout(500)

        submit_btn = page.locator(
            '.ant-modal button[type="submit"], '
            '.ant-modal button:has-text("Log in"), '
            '.ant-modal button:has-text("Log In"), '
            'button[type="submit"], '
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        ).last

        submit_btn.click(force=True, timeout=15000)
        print("✓ Login form submitted.", flush=True)
        page.wait_for_timeout(7000)

    except Exception as e:
        print(f"❌ Login failed: {e}", flush=True)
        try:
            page.screenshot(path="login_failed.png", full_page=True)
            with open("login_failed.html", "w", encoding="utf-8") as f:
                f.write(page.content())
        except Exception:
            pass
        raise e

    print(f"After login URL: {page.url}", flush=True)
    print("✓ LOGGED INTO SEREY SUCCESSFULLY!", flush=True)


# ============================================================
# URL HELPERS
# ============================================================

def normalize_url(url):
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = SEREY + url
    elif not url.startswith("http"):
        return None
    return url.split("#")[0]


def is_real_post_url(url):
    url = normalize_url(url)
    if not url:
        return False

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(":")[0]
        path = parsed.path.rstrip("/")

        if not (host == "serey.io" or host == "www.serey.io" or host.endswith(".serey.io")):
            return False

        bad_parts = [
            "/blog/post/new", "/my-activity", "/activity", "/profile",
            "/posts", "/followers", "/following", "/login", "/register"
        ]

        lower_path = path.lower()
        for bad in bad_parts:
            if bad in lower_path:
                return False

        m = re.match(r"^/authors/([^/]+)/([^/]+)$", path, re.I)
        if not m:
            return False

        username = m.group(1).replace("@", "").lower()
        post_id = m.group(2).lower()
        expected_user = SEREY_LOGIN.replace("@", "").lower()

        if username != expected_user:
            return False

        bad_ids = {
            "my-activity", "activity", "profile", "posts",
            "followers", "following", "write", "new"
        }
        if post_id in bad_ids:
            return False

        return True
    except Exception:
        return False


# ============================================================
# NETWORK CAPTURE
# ============================================================

class NetworkCapture:
    def __init__(self):
        self.responses = []

    def attach(self, page):
        def on_response(response):
            try:
                url = response.url
                method = response.request.method if response.request else ""
                status = response.status

                if (
                    method.upper() in {"POST", "PUT", "PATCH"}
                    or "/api/" in url.lower()
                    or "global-api" in url.lower()
                ):
                    item = {"url": url, "method": method, "status": status, "text": ""}
                    try:
                        content_type = response.headers.get("content-type", "").lower()
                        if "json" in content_type or "/api/" in url.lower():
                            try:
                                item["text"] = response.text()[:20000]
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self.responses.append(item)
            except Exception:
                pass

        page.on("response", on_response)


def extract_urls_from_text(text):
    found = []
    if not text:
        return found
    urls = re.findall(r'https?://[^\s"\'<>]+', text, re.I)
    for url in urls:
        url = url.rstrip(".,;:)]}'\"")
        if is_real_post_url(url):
            found.append(url)
    return found


def collect_urls_from_json(obj):
    found = []
    if obj is None:
        return found
    if isinstance(obj, str):
        found.extend(extract_urls_from_text(obj))
        matches = re.findall(r'["\'](\/authors\/[^"\']+)["\']', obj, re.I)
        for x in matches:
            candidate = normalize_url(x)
            if is_real_post_url(candidate):
                found.append(candidate)
        return found

    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if any(w in key_lower for w in ["url", "link", "slug", "permalink", "post", "article"]):
                if isinstance(value, str):
                    candidate = normalize_url(value)
                    if is_real_post_url(candidate):
                        found.append(candidate)
                    found.extend(extract_urls_from_text(value))
            found.extend(collect_urls_from_json(value))
        return found

    if isinstance(obj, list):
        for item in obj:
            found.extend(collect_urls_from_json(item))
    return found


def analyze_network_responses(capture):
    print("\n" + "=" * 60 + "\nPUBLISH NETWORK RESPONSES\n" + "=" * 60, flush=True)
    real_urls = []

    for i, item in enumerate(capture.responses):
        url = item.get("url", "")
        method = item.get("method", "")
        status = item.get("status", "")
        text = item.get("text", "")

        print(f"[{i+1}] {method} {status} {url}", flush=True)
        if text:
            compact = re.sub(r"\s+", " ", text)
            print(f"    RESPONSE: {compact[:500]}", flush=True)
            real_urls.extend(extract_urls_from_text(text))
            try:
                data = json.loads(text)
                real_urls.extend(collect_urls_from_json(data))
            except Exception:
                pass

    result = []
    for url in real_urls:
        if url not in result and is_real_post_url(url):
            result.append(url)

    print("=" * 60, flush=True)
    if result:
        print("✓ REAL POST URL FOUND IN API:", flush=True)
        for url in result:
            print(url, flush=True)
    else:
        print("No real post URL found in API responses.", flush=True)
    print("=" * 60, flush=True)
    return result


def find_real_post_links(page):
    urls = []
    try:
        links = page.locator('a[href]')
        count = min(links.count(), 500)
        for i in range(count):
            try:
                href = links.nth(i).get_attribute("href")
                candidate = normalize_url(href)
                if is_real_post_url(candidate) and candidate not in urls:
                    urls.append(candidate)
            except Exception:
                continue
    except Exception:
        pass
    return urls


def verify_real_post_page(page, url, title):
    if not is_real_post_url(url):
        return False

    print(f"Verifying candidate post URL: {url}", flush=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        final_url = page.url

        if not is_real_post_url(final_url):
            print("❌ Candidate URL failed URL validation.", flush=True)
            return False

        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=10000)
        except Exception:
            pass

        title_clean = title.strip().lower()
        body_clean = body_text.strip().lower()

        if title_clean and title_clean in body_clean:
            print(f"✓ REAL PUBLISHED POST VERIFIED!\n✓ URL: {final_url}", flush=True)
            return True

        words = [x for x in re.findall(r"\w+", title_clean) if len(x) >= 4]
        if words:
            matched = sum(1 for word in words[:8] if word in body_clean)
            if matched >= max(2, min(4, len(words))):
                print(f"✓ REAL POST VERIFIED (partial title match).\n✓ URL: {final_url}", flush=True)
                return True

        print("❌ URL exists but post title could not be verified.", flush=True)
        return False
    except Exception as e:
        print(f"❌ Post page verification failed: {e}", flush=True)
        return False


def search_activity_for_post(page, title):
    activity_url = f"{SEREY}/authors/{SEREY_LOGIN}/my-activity"
    print("Checking profile activity for a real post link...", flush=True)
    try:
        page.goto(activity_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        links = find_real_post_links(page)
        if links:
            print("Real post links found in activity:", flush=True)
            for link in links:
                print(link, flush=True)
            return links
        return []
    except Exception as e:
        print(f"Activity search failed: {e}", flush=True)
        return []


def close_crop_modal(page):
    try:
        modals = page.locator(".ant-modal-wrap:visible")
        for i in range(modals.count()):
            modal = modals.nth(i)
            text = modal.inner_text().lower() if modal.is_visible() else ""
            if "crop" in text or modal.locator('[data-testid="cropper"]').count() > 0:
                buttons = modal.locator("button")
                for j in range(buttons.count()):
                    btn = buttons.nth(j)
                    if btn.is_visible() and btn.inner_text().strip().lower() in {"ok", "confirm", "done", "save"}:
                        print("✓ Confirming image crop...", flush=True)
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        return
    except Exception:
        pass


def visible_publish_buttons(page):
    result = []
    for selector in ['button', '[role="button"]', 'a']:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 300)):
                el = loc.nth(i)
                if el.is_visible() and el.inner_text().strip().lower() == "publish":
                    result.append(el)
        except Exception:
            continue
    return result


def click_first_publish(page):
    print("Attempting to click first Publish...", flush=True)
    dismiss_overlays(page)

    for attempt in range(5):
        close_crop_modal(page)
        page.wait_for_timeout(1000)
        buttons = visible_publish_buttons(page)
        print(f"Publish buttons detected: {len(buttons)}", flush=True)

        if buttons:
            btn = buttons[0]
            try:
                btn.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            try:
                btn.click(timeout=8000)
            except Exception:
                btn.click(force=True, timeout=8000)

            page.wait_for_timeout(3000)
            if page.locator(".ant-modal-wrap:visible").count() > 0:
                return True
        page.wait_for_timeout(2000)

    return page.locator(".ant-modal-wrap:visible").count() > 0


# ============================================================
# CLICK FINAL PUBLISH (WITH OVERLAY DISMISS & JS TRIGGER)
# ============================================================

def click_final_publish(page):
    print("Searching for final Publish button...", flush=True)
    page.wait_for_timeout(2000)

    # ওভারলে দূর করা যাতে বাটনের উপর ক্লিক আটকায় না
    dismiss_overlays(page)

    modal = page.locator(".ant-modal-wrap:visible").last
    if modal.count() == 0:
        print("❌ Publish modal not found.", flush=True)
        return False

    # নিশ্চিত করুন ক্যাটাগরি সিলেক্টেড আছে
    try:
        select_box = modal.locator(".ant-select-selector")
        if select_box.is_visible():
            select_box.click()
            page.wait_for_timeout(1000)
            options = page.locator(".ant-select-dropdown:visible .ant-select-item-option")
            if options.count() > 0:
                options.first.click()
                print("✓ Verified category selection in modal.", flush=True)
                page.wait_for_timeout(1000)
    except Exception:
        pass

    # ফাইনাল বাটন খোঁজা
    buttons = modal.locator("button")
    candidate = None
    for i in range(buttons.count()):
        btn = buttons.nth(i)
        if btn.is_visible():
            txt = btn.inner_text().strip().lower()
            if txt in {"publish", "submit", "confirm", "পোস্ট করুন"}:
                candidate = btn
                break

    if not candidate:
        candidate = modal.locator("button.ant-btn-primary").last

    if not candidate or not candidate.is_visible():
        print("❌ Final Publish button candidate not visible.", flush=True)
        return False

    # স্ক্রিনের সব ওভারলে বা ব্যাকড্রপ জোর করে সরানো
    dismiss_overlays(page)

    # JavaScript এর মাধ্যমে সরাসরি আসল ক্লিক ট্রিগার করা
    try:
        print("Triggering final Publish click via JavaScript...", flush=True)
        candidate.evaluate("btn => { btn.disabled = false; btn.click(); }")
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print(f"JS Click failed, trying standard click: {e}", flush=True)
        try:
            candidate.click(force=True, timeout=10000)
            return True
        except Exception as e2:
            print(f"Force click failed: {e2}", flush=True)

    return False


def save_debug(page):
    try:
        filename = f"serey_debug_{int(time.time())}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"✓ Debug HTML saved: {filename}", flush=True)
    except Exception as e:
        print(f"Debug save failed: {e}", flush=True)


# ============================================================
# PUBLISH
# ============================================================

def publish(page, post):
    print("-" * 60, flush=True)
    print(f"Publishing: {post['title']} (Steem Date: {post.get('created', 'N/A')})", flush=True)

    # শুরুতেই নেটওয়ার্ক ট্র্যাকিং অন করা যাতে কোনো এপিআই মিস না হয়
    capture = NetworkCapture()
    capture.attach(page)

    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    dismiss_overlays(page)

    # 1. TITLE
    title_box = page.locator(
        'input[placeholder*="title" i], textarea[placeholder*="title" i], input[placeholder*="Enter title" i]'
    ).first
    title_box.wait_for(state="visible", timeout=20000)
    title_box.fill(post["title"])
    print("✓ Title filled", flush=True)

    # 2. BODY
    editor = page.locator('.ql-editor, div[contenteditable="true"]').first
    editor.wait_for(state="visible", timeout=20000)
    try:
        editor.fill(post["body"])
    except Exception:
        editor.click(force=True)
        page.keyboard.insert_text(post["body"])
    print(f"✓ Body filled ({len(post['body'])} characters)", flush=True)
    page.wait_for_timeout(1500)

    # 3. THUMBNAIL
    downloaded_img = download_image(post.get("thumbnail"))
    if downloaded_img:
        try:
            file_inputs = page.locator('input[type="file"]')
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(downloaded_img)
                print("✓ Thumbnail uploaded.", flush=True)
                page.wait_for_timeout(6000)
                close_crop_modal(page)
        except Exception as e:
            print(f"❌ Thumbnail upload failed: {e}", flush=True)

    # 4. FIRST PUBLISH
    if not click_first_publish(page):
        print("❌ Could not open Publish modal.", flush=True)
        save_debug(page)
        return None
    print("✓ Publish modal opened.", flush=True)

    # 5. SELECT CATEGORY IN MODAL
    try:
        page.wait_for_timeout(1500)
        select_btn = page.locator('.ant-modal-wrap:visible .ant-select-selector').first
        if select_btn.is_visible():
            select_btn.click()
            page.wait_for_timeout(1200)
            options = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')
            if options.count() > 0:
                opt = options.first
                opt_name = opt.inner_text().strip()
                opt.click()
                print(f"✓ Category selected: {opt_name}", flush=True)
                page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Category selection note: {e}", flush=True)

    # 6. FINAL PUBLISH
    if not click_final_publish(page):
        print("❌ Final Publish button could not be clicked.", flush=True)
        save_debug(page)
        return None

    print("Waiting for Serey publish response...", flush=True)

    # 7. URL পরিবর্তন বা API রেসপন্সের জন্য অপেক্ষা
    for i in range(25):
        page.wait_for_timeout(1000)
        print(f"Waiting... {i+1}/25 sec | URL: {page.url}", flush=True)

        if is_real_post_url(page.url):
            print("✓ REAL POST URL detected immediately.", flush=True)
            candidate = page.url
            if verify_real_post_page(page, candidate, post["title"]):
                if downloaded_img and os.path.exists(downloaded_img):
                    os.remove(downloaded_img)
                return candidate

    # এপিআই রেসপন্স অ্যানালাইসিস
    api_urls = analyze_network_responses(capture)
    for candidate in api_urls:
        if verify_real_post_page(page, candidate, post["title"]):
            if downloaded_img and os.path.exists(downloaded_img):
                os.remove(downloaded_img)
            return candidate

    # অ্যাক্টিভিটি পেজ চেক
    activity_links = search_activity_for_post(page, post["title"])
    for candidate in activity_links:
        if verify_real_post_page(page, candidate, post["title"]):
            if downloaded_img and os.path.exists(downloaded_img):
                os.remove(downloaded_img)
            return candidate

    print("\n" + "=" * 60 + "\n❌ PUBLISH COULD NOT BE VERIFIED\n" + "=" * 60, flush=True)
    save_debug(page)
    if downloaded_img and os.path.exists(downloaded_img):
        try:
            os.remove(downloaded_img)
        except Exception:
            pass
    return None


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("STEEM -> BENGALI SEREY AUTO SYNC")
    print("LAST 365 DAYS -> OLDEST TO NEWEST")
    print("=" * 60)

    if not STEEM_USERNAME or not SEREY_LOGIN or not SEREY_PASSWORD:
        print("❌ Error: Missing Environment Secrets!", flush=True)
        return

    synced = load_synced()
    print(f"Previously synced: {len(synced)}", flush=True)

    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced]
    print(f"Unsynced posts remaining (Last 1 Year): {len(new_posts)}", flush=True)

    posts_to_run = new_posts[:POSTS_PER_RUN]
    if not posts_to_run:
        print("No new posts to publish.", flush=True)
        return

    for p in posts_to_run:
        print(f"Selected: {p['id']}\nCreated: {p['created']}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )

        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        try:
            login(page)

            for post in posts_to_run:
                try:
                    published_url = publish(page, post)
                    if published_url and is_real_post_url(published_url):
                        print("\n✓✓✓ PUBLISHED SUCCESSFULLY ✓✓✓", flush=True)
                        print(f"Published URL: {published_url}", flush=True)
                        synced.add(post["id"])
                        save_synced(synced)
                        print(f"✓ SAVED AS SYNCED: {post['id']}", flush=True)
                    else:
                        print(f"\n⚠ FAILED: {post['id']}", flush=True)
                except Exception as e:
                    print(f"❌ Publish error: {e}", flush=True)
        finally:
            browser.close()

    print("\n" + "=" * 60 + "\nRUN FINISHED\n" + "=" * 60)


if __name__ == "__main__":
    main()
