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

# IMPORTANT:
# This sync is for Bengali Serey.
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
        meta = json.loads(
            metadata or "{}"
        )

        images = meta.get(
            "image",
            []
        )

        if isinstance(images, list):
            for x in images:
                if (
                    isinstance(x, str)
                    and x.startswith("http")
                ):
                    thumbnail = x
                    break

    except Exception:
        pass

    if not thumbnail:
        m = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)',
            body,
            re.I
        )
        if m:
            thumbnail = m.group(1)

    if not thumbnail:
        m = re.search(
            r'<img[^>]+src=["\']'
            r'(https?://[^"\'>\s]+)',
            body,
            re.I
        )
        if m:
            thumbnail = m.group(1)

    if not thumbnail:
        m = re.search(
            r'(https?://\S+\.(?:jpg|jpeg|png|gif|webp)'
            r'(?:\?\S*)?)',
            body,
            re.I
        )
        if m:
            thumbnail = m.group(1)

    # Clean body
    body = re.sub(
        r'!\[[^\]]*\]\(\s*https?://[^)\s]+\s*\)',
        '',
        body,
        flags=re.I
    )

    body = re.sub(
        r'<img\b[^>]*>',
        '',
        body,
        flags=re.I
    )

    body = re.sub(
        r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)'
        r'(?:\?\S*)?',
        '',
        body,
        flags=re.I
    )

    body = re.sub(
        r'<[^>]+>',
        '',
        body
    )

    body = re.sub(
        r'^\s{0,3}#{1,6}\s*',
        '',
        body,
        flags=re.M
    )

    body = re.sub(
        r'\*\*(.*?)\*\*',
        r'\1',
        body,
        flags=re.S
    )

    body = re.sub(
        r'(?<!\*)\*(.*?)\*(?!\*)',
        r'\1',
        body,
        flags=re.S
    )

    body = re.sub(
        r'\[([^\]]+)\]\((https?://[^)]+)\)',
        r'\1',
        body,
        flags=re.I
    )

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
        return datetime.strptime(
            date_str,
            "%Y-%m-%dT%H:%M:%S"
        ).replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return None


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    print(
        f"Collecting posts from @{STEEM_USERNAME} "
        f"for the last {DAYS_LIMIT} days...",
        flush=True
    )

    cutoff_date = (
        datetime.now(timezone.utc)
        - timedelta(days=DAYS_LIMIT)
    )

    print(
        f"Post cut-off date: "
        f"{cutoff_date.strftime('%Y-%m-%d')}",
        flush=True
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None
    reached_old = False

    while (
        len(posts) < 5000
        and not reached_old
    ):

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

        batch = (
            result[1:]
            if start_author
            else result
        )

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

            body, thumbnail = (
                extract_thumbnail_and_body(
                    p.get("body", ""),
                    p.get("json_metadata", "{}")
                )
            )

            posts.append(
                {
                    "id": post_id,
                    "title": p.get("title", "").strip(),
                    "body": body,
                    "thumbnail": thumbnail,
                    "created": created_str,
                    "category": p.get("category", "")
                }
            )

        last = result[-1]
        new_author = last.get("author")
        new_permlink = last.get("permlink")

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if (
            len(result) < 100
            or reached_old
        ):
            break

        time.sleep(0.3)

    posts.reverse()

    print(
        f"Total posts collected from the last "
        f"{DAYS_LIMIT} days: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    if not url:
        return None

    try:
        print(
            f"Downloading cover thumbnail: {url}",
            flush=True
        )

        headers = {
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36",
            "Referer":
                "https://steemit.com/"
        }

        r = requests.get(
            url,
            timeout=25,
            headers=headers
        )

        r.raise_for_status()

        content_type = (
            r.headers
            .get("content-type", "")
            .lower()
        )

        ext = (
            mimetypes.guess_extension(
                content_type.split(";")[0]
            )
            or ".jpg"
        )

        if ext == ".jpe":
            ext = ".jpg"

        file_path = f"{TEMP_IMAGE_PREFIX}{ext}"

        with open(file_path, "wb") as f:
            f.write(r.content)

        print(
            f"✓ Cover image saved: "
            f"{file_path} "
            f"({len(r.content)} bytes)",
            flush=True
        )

        return file_path

    except Exception as e:
        print(
            f"❌ Cover image download failed: {e}",
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

    page.wait_for_timeout(5000)

    login_buttons = page.locator(
        'a:has-text("Log in"), '
        'button:has-text("Log in"), '
        'a:has-text("Log In"), '
        'button:has-text("Log In")'
    )

    if (
        login_buttons.count() > 0
        and login_buttons.first.is_visible()
    ):

        try:
            login_buttons.first.click(
                force=True,
                timeout=15000
            )
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Login button click note: {e}", flush=True)

        user_in = page.locator(
            'input[placeholder*="Username" i], '
            'input[type="text"]'
        ).first

        pass_in = page.locator(
            'input[placeholder*="Private Key" i], '
            'input[placeholder*="Password" i], '
            'input[type="password"]'
        ).first

        user_in.wait_for(state="visible", timeout=20000)
        pass_in.wait_for(state="visible", timeout=20000)

        user_in.fill(SEREY_LOGIN)
        pass_in.fill(SEREY_PASSWORD)

        page.locator(
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        ).last.click(
            force=True,
            timeout=20000
        )

        page.wait_for_timeout(7000)

    print(
        f"After login URL: {page.url}",
        flush=True
    )

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )


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
        path = parsed.path.rstrip("/")

        bad_parts = [
            "/blog/post/new",
            "/my-activity",
            "/activity",
            "/profile",
            "/posts",
            "/followers",
            "/following",
            "/login",
            "/register"
        ]

        lower_path = path.lower()
        for bad in bad_parts:
            if bad in lower_path:
                return False

        m = re.match(
            r"^/authors/([^/]+)/([^/]+)$",
            path,
            re.I
        )

        if not m:
            return False

        username = (
            m.group(1)
            .replace("@", "")
            .lower()
        )

        expected_user = (
            SEREY_LOGIN
            .replace("@", "")
            .lower()
        )

        if username != expected_user:
            return False

        return True

    except Exception:
        return False


# ============================================================
# CLOSE CROP MODAL & WAIT UNTIL COMPLETELY CLOSED
# ============================================================

def close_crop_modal(page):

    try:
        modals = page.locator(".ant-modal-wrap:visible, div[role=\"dialog\"]:visible")
        count = modals.count()

        if count == 0:
            return

        for i in range(count):
            modal = modals.nth(i)
            try:
                text = modal.inner_text(timeout=1000).lower()
            except Exception:
                text = ""

            if (
                "crop" in text
                or modal.locator('[data-testid="cropper"]').count() > 0
            ):
                buttons = modal.locator("button")
                for j in range(buttons.count()):
                    try:
                        btn = buttons.nth(j)
                        if not btn.is_visible():
                            continue

                        txt = btn.inner_text().strip().lower()
                        if txt in {"ok", "confirm", "done", "save", "নিশ্চিত করুন"}:
                            print("✓ Confirming image crop...", flush=True)
                            btn.click(force=True)
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue

        # নিশ্চিত করা যে ক্রপ মডালের পর্দা স্ক্রিন থেকে পুরোপুরি গায়েব হয়েছে
        for _ in range(8):
            if page.locator('.ant-modal-wrap:visible, div[role="dialog"]:visible').count() == 0:
                break
            page.wait_for_timeout(500)

    except Exception:
        pass


# ============================================================
# CLICK FIRST PUBLISH
# ============================================================

def click_first_publish(page):

    print("Attempting to click first Publish...", flush=True)

    for attempt in range(5):

        buttons = page.locator('button:has-text("Publish"), a:has-text("Publish"), [role="button"]:has-text("Publish")')
        count = buttons.count()

        print(f"Publish buttons detected: {count}", flush=True)

        if count > 0:
            btn = buttons.first
            try:
                btn.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            try:
                btn.click(force=True, timeout=10000)
                print("✓ First Publish clicked normally.", flush=True)
                page.wait_for_timeout(3000)

                # নিশ্চিতভাবে চেক করা আসল পাবলিশ মডাল ওপেন হয়েছে কিনা
                if page.locator('.ant-modal-wrap:visible, div[role="dialog"]:visible').count() > 0:
                    return True
            except Exception as e:
                print(f"Publish click attempt {attempt+1} note: {e}", flush=True)

        page.wait_for_timeout(2000)

    return (
        page.locator('.ant-modal-wrap:visible, div[role="dialog"]:visible').count() > 0
    )


# ============================================================
# CLICK FINAL PUBLISH WITH RECOVERY
# ============================================================

def click_final_publish(page):

    print("Searching for final Publish button...", flush=True)
    page.wait_for_timeout(1500)

    # যদি কোনো কারণে মডাল বন্ধ হয়ে যায়, আবার First Publish চেপে ওপেন করা
    if page.locator('.ant-modal-wrap:visible, div[role="dialog"]:visible').count() == 0:
        print("⚠️ Modal was dismissed, recovering by re-clicking first Publish...", flush=True)
        btn = page.locator('button:has-text("Publish"), [role="button"]:has-text("Publish")').first
        if btn.is_visible():
            btn.click(force=True)
            page.wait_for_timeout(3000)

    modal = page.locator('.ant-modal-wrap:visible, div[role="dialog"]:visible').last

    if modal.count() == 0:
        print("❌ Publish modal not found.", flush=True)
        return False

    buttons = modal.locator("button")
    candidates = []

    for i in range(buttons.count()):
        try:
            btn = buttons.nth(i)
            if not btn.is_visible():
                continue

            txt = btn.inner_text().strip().lower()
            if txt in {"publish", "submit", "confirm", "প্রকাশ করুন"}:
                candidates.append(btn)
        except Exception:
            continue

    print(f"Final modal action buttons: {len(candidates)}", flush=True)

    if not candidates:
        candidates = [modal.locator("button.ant-btn-primary").last]

    for btn in reversed(candidates):
        try:
            print("Trying final Publish click...", flush=True)
            btn.scroll_into_view_if_needed(timeout=5000)
            btn.click(force=True, timeout=10000)
            print("✓ FINAL PUBLISH CLICKED.", flush=True)
            return True
        except Exception as e:
            print(f"Final click error: {e}", flush=True)

    return False


# ============================================================
# SAVE DEBUG HTML
# ============================================================

def save_debug(page):

    try:
        filename = f"serey_debug_{int(time.time())}.html"
        html = page.content()
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✓ Debug HTML saved: {filename}", flush=True)
    except Exception:
        pass


# ============================================================
# VERIFY REAL POST PAGE
# ============================================================

def verify_real_post_page(page, url, title):

    if not is_real_post_url(url):
        return False

    print(f"Verifying candidate post URL: {url}", flush=True)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        final_url = page.url
        print(f"Verification URL: {final_url}", flush=True)

        if not is_real_post_url(final_url):
            return False

        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=10000)
        except Exception:
            pass

        title_clean = title.strip().lower()
        body_clean = body_text.strip().lower()

        if title_clean and title_clean in body_clean:
            print("✓ REAL PUBLISHED POST VERIFIED!", flush=True)
            print(f"✓ URL: {final_url}", flush=True)
            return True

        words = [x for x in re.findall(r"\w+", title_clean) if len(x) >= 4]
        if words:
            matched = sum(1 for word in words[:8] if word in body_clean)
            if matched >= max(2, min(4, len(words))):
                print("✓ REAL POST VERIFIED (partial title match).", flush=True)
                print(f"✓ URL: {final_url}", flush=True)
                return True

        return False

    except Exception as e:
        print(f"❌ Post page verification failed: {e}", flush=True)
        return False


# ============================================================
# PUBLISH
# ============================================================

def publish(page, post):

    print("-" * 60, flush=True)
    print(
        f"Publishing: {post['title']} "
        f"(Steem Date: {post.get('created', 'N/A')})",
        flush=True
    )

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    # 1. TITLE
    title_box = page.locator(
        'input[placeholder*="title" i], '
        'textarea[placeholder*="title" i], '
        'input[placeholder*="Enter title" i]'
    ).first

    title_box.wait_for(state="visible", timeout=20000)
    title_box.fill(post["title"])
    print("✓ Title filled", flush=True)

    # 2. BODY
    editor = page.locator(
        '.ql-editor, '
        'div[contenteditable="true"]'
    ).first

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
            count = file_inputs.count()
            print(f"File inputs detected: {count}", flush=True)

            if count > 0:
                file_inputs.first.set_input_files(downloaded_img)
                print("✓ Thumbnail uploaded.", flush=True)
                page.wait_for_timeout(4000)

                # ক্রপ মডাল নিশ্চিত করা
                close_crop_modal(page)
                print("✓ Thumbnail processing finished.", flush=True)
                page.wait_for_timeout(2000)
        except Exception as e:
            print(f"❌ Thumbnail note: {e}", flush=True)

    # 4. FIRST PUBLISH
    if not click_first_publish(page):
        print("❌ Could not open Publish modal.", flush=True)
        save_debug(page)
        return None

    print("✓ Publish modal opened.", flush=True)

    # 5. CATEGORY SELECTION IN MODAL
    try:
        modal = page.locator('.ant-modal-wrap:visible, div[role="dialog"]:visible').last
        select_btn = modal.locator('.ant-select-selector:visible, .ant-select:visible').first
        if select_btn.is_visible():
            select_btn.click(force=True)
            page.wait_for_timeout(1200)

            options = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, [role="option"]:visible')
            if options.count() > 0:
                option_name = options.first.inner_text().strip()
                options.first.click(force=True)
                print(f"✓ Category selected: {option_name}", flush=True)
                page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Category selection note: {e}", flush=True)

    # 6. FINAL PUBLISH
    if not click_final_publish(page):
        print("❌ Final Publish button could not be clicked.", flush=True)
        save_debug(page)
        return None

    print("Waiting for Serey publish response...", flush=True)

    # 7. REDIRECT VERIFICATION
    for i in range(25):
        page.wait_for_timeout(1000)
        print(f"Waiting... {i+1}/25 sec | URL: {page.url}", flush=True)

        if is_real_post_url(page.url):
            print("✓ REAL POST URL detected immediately.", flush=True)
            candidate = page.url
            if verify_real_post_page(page, candidate, post["title"]):
                if downloaded_img and os.path.exists(downloaded_img):
                    try:
                        os.remove(downloaded_img)
                    except Exception:
                        pass
                return candidate

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

    if (
        not STEEM_USERNAME
        or not SEREY_LOGIN
        or not SEREY_PASSWORD
    ):
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
        print(f"Selected: {p['id']}", flush=True)
        print(f"Created: {p['created']}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            login(page)

            for post in posts_to_run:
                try:
                    published_url = publish(page, post)
                    if published_url and is_real_post_url(published_url):
                        print("", flush=True)
                        print("✓✓✓ PUBLISHED SUCCESSFULLY ✓✓✓", flush=True)
                        print(f"Published URL: {published_url}", flush=True)

                        synced.add(post["id"])
                        save_synced(synced)
                        print(f"✓ SAVED AS SYNCED: {post['id']}", flush=True)
                    else:
                        print("", flush=True)
                        print(f"⚠ FAILED: {post['id']}", flush=True)
                        print("⚠ This post will NOT be added to synced_posts.json.", flush=True)

                except Exception as e:
                    print(f"❌ Publish error: {e}", flush=True)
                    print(f"⚠ FAILED: {post['id']}", flush=True)

        finally:
            browser.close()

    print("", flush=True)
    print("=" * 60)
    print("RUN FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()
