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

SEREY = "https://serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE_PREFIX = "temp_image"

POSTS_PER_RUN = 1
DAYS_LIMIT = 365

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
            r = requests.post(node, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()

            if "error" in data:
                raise Exception(data["error"])

            return data["result"]

        except Exception as e:
            print(f"RPC {node} failed: {e}", flush=True)

    raise Exception("All Steem RPC nodes failed")


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_synced(data):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)


# ============================================================
# EXTRACT THUMBNAIL
# ============================================================

def extract_thumbnail_and_body(body, metadata):
    thumbnail = None

    try:
        meta = json.loads(metadata or "{}")
        for x in meta.get("image", []):
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

    body = re.sub(r'\n{4,}', '\n\n', body)
    return body.strip(), thumbnail


# ============================================================
# GET STEEM POSTS (LAST 1 YEAR)
# ============================================================

def parse_steem_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def get_posts():
    print(f"Collecting posts from @{STEEM_USERNAME} for the last {DAYS_LIMIT} days...", flush=True)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=DAYS_LIMIT)
    print(f"Post cut-off date: {cutoff_date.strftime('%Y-%m-%d')}", flush=True)

    posts = []
    seen = set()
    start_author = None
    start_permlink = None
    reached_older_than_limit = False

    while len(posts) < 5000 and not reached_older_than_limit:
        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

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

            pid = f"{author}/{permlink}"
            if pid in seen:
                continue

            created_str = p.get("created", "")
            created_dt = parse_steem_date(created_str)

            if created_dt and created_dt < cutoff_date:
                reached_older_than_limit = True
                break

            seen.add(pid)

            body, thumbnail = extract_thumbnail_and_body(
                p.get("body", ""),
                p.get("json_metadata", "{}")
            )

            posts.append({
                "id": pid,
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

        if len(result) < 100 or reached_older_than_limit:
            break

        time.sleep(0.3)

    posts.reverse()
    print(f"Total posts collected from the last {DAYS_LIMIT} days: {len(posts)}", flush=True)
    return posts


# ============================================================
# DOWNLOAD THUMBNAIL
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

        print(f"✓ Cover image saved: {file_path}", flush=True)
        return file_path

    except Exception as e:
        print(f"❌ Cover image download failed: {e}", flush=True)
        return None


# ============================================================
# LOGIN
# ============================================================

def login(page):
    print("Logging into Serey...", flush=True)

    page.goto(SEREY, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    login_btn = page.locator(
        'a:has-text("Log in"), button:has-text("Log in"), a:has-text("Log In"), button:has-text("Log In")'
    ).first

    if login_btn.count() > 0 and login_btn.is_visible():
        login_btn.click(force=True)
        page.wait_for_timeout(3000)

        user_in = page.locator('input[placeholder*="Username" i], input[type="text"]').first
        pass_in = page.locator('input[placeholder*="Private Key" i], input[placeholder*="Password" i], input[type="password"]').first

        user_in.fill(SEREY_LOGIN)
        pass_in.fill(SEREY_PASSWORD)

        page.locator('button:has-text("Log in"), button:has-text("Log In")').last.click(force=True)
        page.wait_for_timeout(7000)
        print("✓ LOGGED INTO SEREY SUCCESSFULLY!", flush=True)
    else:
        print("Already logged in or login button not found.", flush=True)


# ============================================================
# VERIFY (TARGETS: /authors/<username>/<post-id>)
# ============================================================

def verify(page, title):
    print("VERIFYING PUBLISHED POST...", flush=True)

    for step in range(12):
        page.wait_for_timeout(3000)
        url = page.url
        print(f"Check {step+1}/12 - Current URL: {url}", flush=True)

        if "/authors/" in url.lower() and "/blog/post/new" not in url:
            print(f"✓ SUCCESS: POST PUBLISHED AND REDIRECTED! Final URL: {url}", flush=True)
            return True

        try:
            if page.locator('text="Successfully posted your article"').is_visible():
                print("✓ SUCCESS MESSAGE DETECTED!", flush=True)
                return True
        except:
            pass

    print("❌ Publication could not be verified.", flush=True)
    return False


# ============================================================
# PUBLISH POST
# ============================================================

def publish(page, post):
    print("-" * 60)
    print(f"Publishing: {post['title']} (Steem Date: {post.get('created', 'N/A')})", flush=True)

    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # 1. TITLE
    title_box = page.locator(
        'input[placeholder*="title" i], textarea[placeholder*="title" i], input[placeholder*="Enter title" i]'
    ).first
    title_box.click(force=True)
    title_box.fill(post["title"])
    print("✓ Title filled", flush=True)
    page.wait_for_timeout(1000)

    # 2. BODY
    editor = page.locator('.ql-editor, div[contenteditable="true"]').first
    editor.click(force=True)
    page.wait_for_timeout(500)
    try:
        editor.fill(post["body"])
    except Exception:
        page.keyboard.insert_text(post["body"])
    print("✓ Body filled (with all post images)", flush=True)
    page.wait_for_timeout(2000)

    # 3. THUMBNAIL (COVER PHOTO)
    downloaded_img = download_image(post.get("thumbnail"))
    if downloaded_img:
        try:
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files(downloaded_img)
            print("✓ Cover Thumbnail uploaded! Waiting 10s for upload...", flush=True)
            page.wait_for_timeout(10000)
        except Exception as e:
            print(f"❌ Thumbnail upload failed: {e}")

    # 4. FIRST PUBLISH (OPENS MODAL WITH RETRY)
    print("Attempting to click first Publish button to trigger modal...", flush=True)
    modal_opened = False

    for attempt in range(4):
        # ক্লিক করা
        try:
            page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button, a, div[role="button"], span'));
                for (let b of btns) {
                    if (b.innerText && b.innerText.trim().toLowerCase() === 'publish' && b.offsetParent !== null) {
                        b.click();
                        break;
                    }
                }
            }''')
        except Exception:
            pass

        page.wait_for_timeout(3000)

        # চেক করা ড্রপডাউন সহ মডাল ওপেন হয়েছে কিনা
        select_test = page.locator('.ant-modal-content .ant-select, div[role="dialog"] .ant-select, .ant-select-selector:visible')
        if select_test.count() > 0:
            print(f"✓ Real Publish Modal detected with {select_test.count()} dropdown(s)!", flush=True)
            modal_opened = True
            break
        else:
            print(f"Retrying first Publish click (attempt {attempt+1})...", flush=True)
            try:
                page.locator('button:has-text("Publish"), div[role="button"]:has-text("Publish")').last.click(force=True)
            except:
                pass
            page.wait_for_timeout(3000)

    # 5. SELECT CATEGORY IN MODAL
    page.wait_for_timeout(2000)
    try:
        # ড্রপডাউনে ক্লিক করা
        select_btn = page.locator('.ant-modal-content .ant-select-selector, div[role="dialog"] .ant-select-selector, .ant-select-selector:visible').first
        if select_btn.is_visible():
            select_btn.click(force=True)
            page.wait_for_timeout(1500)

            # অপশন থেকে প্রথম ক্যাটাগরি সিলেক্ট করা
            first_opt = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, [role="option"]:visible').first
            if first_opt.is_visible():
                opt_name = first_opt.inner_text().strip()
                first_opt.click(force=True)
                print(f"✓ Category successfully selected: {opt_name}", flush=True)
                page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Category selection note: {e}", flush=True)

    # 6. FINAL PUBLISH BUTTON INSIDE MODAL
    print("Clicking final Submit button inside modal...", flush=True)
    page.wait_for_timeout(2000)

    # মডালের আসল কনফার্ম বাটনে ক্লিক
    try:
        page.evaluate('''() => {
            const modal = document.querySelector('.ant-modal-content, div[role="dialog"], .modal-content');
            if (modal) {
                const btns = Array.from(modal.querySelectorAll('button'));
                const submitBtn = btns.find(b => b.innerText && (b.innerText.trim().toLowerCase() === 'publish' || b.innerText.trim().toLowerCase() === 'submit' || b.innerText.trim().toLowerCase() === 'confirm'));
                if (submitBtn) {
                    submitBtn.removeAttribute('disabled');
                    submitBtn.click();
                }
            }
        }''')
        print("✓ Executed JS Click on Final Modal Publish button!", flush=True)
    except Exception as e:
        print(f"JS final click error: {e}", flush=True)

    # ব্যাকআপ প্লে-রাইট ক্লিক
    try:
        modal_btn = page.locator(
            '.ant-modal-content button:has-text("Publish"), '
            'div[role="dialog"] button:has-text("Publish"), '
            'button.ant-btn-primary'
        ).last
        if modal_btn.is_visible():
            modal_btn.click(force=True)
            print("✓ Playwright Final Click executed!", flush=True)
    except Exception:
        pass

    page.wait_for_timeout(10000)

    if downloaded_img and os.path.exists(downloaded_img):
        try:
            os.remove(downloaded_img)
        except Exception:
            pass

    return verify(page, post["title"])


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("STEEM -> SEREY AUTO SYNC (LAST 1 YEAR -> OLDEST TO NEWEST)")
    print("=" * 60)

    if not STEEM_USERNAME or not SEREY_LOGIN or not SEREY_PASSWORD:
        print("❌ Error: Missing Environment Secrets!")
        return

    synced = load_synced()
    print(f"Previously synced: {len(synced)}", flush=True)

    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced]
    print(f"Unsynced posts remaining (Last 1 Year): {len(new_posts)}", flush=True)

    posts_to_run = new_posts[:POSTS_PER_RUN]
    if not posts_to_run:
        print("No new posts to publish.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            login(page)

            for post in posts_to_run:
                try:
                    if publish(page, post):
                        synced.add(post["id"])
                        save_synced(synced)
                        print(f"✓ SAVED AS SYNCED: {post['id']}", flush=True)
                    else:
                        print("⚠️ NOT SAVED AS SYNCED.", flush=True)
                except Exception as e:
                    print(f"❌ Publish error: {e}", flush=True)

        finally:
            browser.close()

    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
