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

# কত দিন আগের পোস্ট থেকে শুরু করবে (১ বছর = ৩৬৫ দিন)
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
# EXTRACT FIRST IMAGE AS THUMBNAIL
# ============================================================

def extract_thumbnail_and_body(body, metadata):
    thumbnail = None

    # 1. Metadata image
    try:
        meta = json.loads(metadata or "{}")
        for x in meta.get("image", []):
            if isinstance(x, str) and x.startswith("http"):
                thumbnail = x
                break
    except Exception:
        pass

    # 2. First Markdown image
    if not thumbnail:
        m = re.search(r'!\[[^\]]*\]\((https?://[^)\s]+)', body, re.I)
        if m:
            thumbnail = m.group(1)

    # 3. First HTML img
    if not thumbnail:
        m = re.search(r'<img[^>]+src=["\'](https?://[^"\'>\s]+)', body, re.I)
        if m:
            thumbnail = m.group(1)

    # 4. Direct image link
    if not thumbnail:
        m = re.search(r'(https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?)', body, re.I)
        if m:
            thumbnail = m.group(1)

    # Clean excessive empty lines (Keep all text and image markdown intact)
    body = re.sub(r'\n{4,}', '\n\n', body)

    return body.strip(), thumbnail


# ============================================================
# GET STEEM POSTS (LAST 1 YEAR -> OLDEST TO NEWEST)
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
            # Skip reblogs (only author's own posts)
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

            # Check 1-year cutoff
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

    # Reverse list: ১ বছর আগের পুরোনো পোস্ট আগে থাকবে, নতুন পোস্ট পরে আসবে
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

        print(f"✓ Cover image downloaded: {file_path}", flush=True)
        return file_path

    except Exception as e:
        print(f"❌ Cover image download error: {e}", flush=True)
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
# VERIFY URL & PUBLICATION
# ============================================================

def verify(page, title):
    print("VERIFYING PUBLISHED POST...", flush=True)

    for _ in range(8):
        page.wait_for_timeout(4000)
        url = page.url
        print(f"Current URL: {url}", flush=True)

        # চেক করবে URL-এ /authors/ এবং ইউজারনেম/পোস্ট আইডি আছে কিনা
        if "/authors/" in url and "/blog/post/new" not in url:
            print(f"✓ SUCCESS: POST PUBLISHED! Final URL: {url}", flush=True)
            return True

        try:
            if page.locator('text="Successfully posted your article"').is_visible():
                print("✓ SUCCESS MESSAGE DETECTED!", flush=True)
                return True
        except:
            pass

    # পেজে কোনো এরর মেসেজ থাকলে তা প্রিন্ট করা
    try:
        errors = page.locator('.ant-message-error, .ant-form-item-explain-error, .error').all_inner_texts()
        if errors:
            print(f"⚠️ Page Errors: {errors}", flush=True)
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

    # 1. TITLE (Strictly ignores Quill formula inputs)
    title_box = page.locator(
        'input[placeholder*="title" i], textarea[placeholder*="title" i], input[placeholder*="Enter title" i]'
    ).first
    title_box.click(force=True)
    title_box.fill(post["title"])
    print("✓ Title filled", flush=True)
    page.wait_for_timeout(1000)

    # 2. BODY (Keeps all original images and text intact)
    editor = page.locator('.ql-editor, div[contenteditable="true"]').first
    editor.click(force=True)
    page.wait_for_timeout(500)
    try:
        editor.fill(post["body"])
    except Exception:
        page.keyboard.insert_text(post["body"])
    print("✓ Body filled (with all post images)", flush=True)
    page.wait_for_timeout(2000)

    # 3. THUMBNAIL (First image as cover)
    downloaded_img = download_image(post.get("thumbnail"))
    if downloaded_img:
        try:
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files(downloaded_img)
            print("✓ Cover Thumbnail uploaded! Waiting for Serey upload...", flush=True)
            page.wait_for_timeout(7000)
        except Exception as e:
            print(f"❌ Thumbnail upload failed: {e}")

    # 4. FIRST PUBLISH (Opens Modal)
    print("Clicking first Publish button...", flush=True)
    page.locator(
        'button:has-text("Publish"), div[role="button"]:has-text("Publish"), span:has-text("Publish")'
    ).last.click(force=True)

    page.wait_for_timeout(4000)

    # 5. MODAL & AUTO-CATEGORY HANDLING
    modal = page.locator('div[role="dialog"], .ant-modal-content, .modal-content').last
    try:
        modal.wait_for(state="visible", timeout=7000)
        print("✓ Modal detected!", flush=True)
    except Exception:
        print("Modal wait continuing...", flush=True)

    # Ensure Category is selected in modal
    try:
        select_boxes = modal.locator('.ant-select, .ant-select-selector, [role="combobox"]')
        if select_boxes.count() > 0:
            select_boxes.first.click(force=True)
            page.wait_for_timeout(1200)

            options = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) [role="option"], .ant-select-item-option')
            if options.count() > 0:
                opt_txt = options.first.inner_text().strip()
                options.first.click(force=True)
                print(f"✓ Category selected: {opt_txt}", flush=True)
                page.wait_for_timeout(1000)

        # Subcategory selection if present
        if select_boxes.count() > 1:
            select_boxes.nth(1).click(force=True)
            page.wait_for_timeout(1000)
            sub_opts = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) [role="option"], .ant-select-item-option')
            if sub_opts.count() > 0:
                sub_opts.first.click(force=True)
                print("✓ Subcategory selected", flush=True)
                page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Category selection note: {e}", flush=True)

    # 6. FINAL PUBLISH BUTTON
    print("Clicking final Modal Publish button...", flush=True)
    modal_button = modal.locator(
        'button:has-text("Publish"), '
        'button.ant-btn-primary, '
        'button:has-text("Confirm"), '
        'button:has-text("Submit")'
    ).last

    # Wait until button is enabled
    for _ in range(6):
        if modal_button.is_enabled():
            break
        page.wait_for_timeout(1000)

    modal_button.click(force=True)
    print("✓ FINAL PUBLISH CLICKED!", flush=True)

    page.wait_for_timeout(10000)

    # Clean up local thumbnail file
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
        print("❌ Error: Missing Environment Secrets (STEEM_USERNAME, SEREY_LOGIN, SEREY_PASSWORD)!")
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
