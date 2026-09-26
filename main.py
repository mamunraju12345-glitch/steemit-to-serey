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
SEREY_LOGIN = os.environ.get("SEREY_LOGIN", os.environ.get("SEREY_USERNAME", "")).replace("@", "").strip()
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
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    for node in STEEM_NODES:
        try:
            r = requests.post(node, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise Exception(data["error"])
            print(f"✓ RPC success: {node}", flush=True)
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
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()

def save_synced(data):
    temp_file = SYNC_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)
    os.replace(temp_file, SYNC_FILE)

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

    body = re.sub(r'!\[[^\]]*\]\(\s*https?://[^)\s]+\s*\)', '', body, flags=re.I)
    body = re.sub(r'<img\b[^>]*>', '', body, flags=re.I)
    body = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?', '', body, flags=re.I)
    body = re.sub(r'<[^>]+>', '', body)
    body = re.sub(r'^\s{0,3}#{1,6}\s*', '', body, flags=re.M)
    body = re.sub(r'\*\*(.*?)\*\*', r'\1', body, flags=re.S)
    body = re.sub(r'(?<!\*)\*(.*?)\*(?!\*)', r'\1', body, flags=re.S)
    body = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1', body, flags=re.I)

    lines = [line.strip() for line in body.splitlines() if line.strip() and not re.fullmatch(r'https?://\S+', line.strip(), re.I)]
    body = "\n\n".join(lines)
    return body.strip(), thumbnail

def parse_steem_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def get_posts():
    print(f"Collecting posts from @{STEEM_USERNAME} for the last {DAYS_LIMIT} days...", flush=True)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=DAYS_LIMIT)
    posts, seen = [], set()
    start_author, start_permlink, reached_old = None, None, False

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
            body, thumbnail = extract_thumbnail_and_body(p.get("body", ""), p.get("json_metadata", "{}"))
            posts.append({
                "id": post_id,
                "title": p.get("title", "").strip(),
                "body": body,
                "thumbnail": thumbnail,
                "created": created_str,
                "category": p.get("category", "")
            })

        last = result[-1]
        if last.get("author") == start_author and last.get("permlink") == start_permlink:
            break
        start_author, start_permlink = last.get("author"), last.get("permlink")
        if len(result) < 100 or reached_old:
            break
        time.sleep(0.3)

    posts.reverse()
    print(f"Total posts collected: {len(posts)}", flush=True)
    return posts

def download_image(url):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://steemit.com/"})
        r.raise_for_status()
        ext = mimetypes.guess_extension(r.headers.get("content-type", "").split(";")[0]) or ".jpg"
        file_path = f"{TEMP_IMAGE_PREFIX}{ext}"
        with open(file_path, "wb") as f:
            f.write(r.content)
        return file_path
    except Exception as e:
        print(f"Image download failed: {e}", flush=True)
        return None

# ============================================================
# DISMISS OVERLAYS & MODALS
# ============================================================

def dismiss_overlays(page):
    try:
        page.evaluate("""
            () => {
                const overlays = document.querySelectorAll(
                    '[class*="cookie"], [id*="cookie"], .no-cookie-notice-overlay, [class*="notice-overlay"]'
                );
                overlays.forEach(el => el.remove());
            }
        """)
        page.wait_for_timeout(300)
    except Exception:
        pass

def handle_crop_modal(page):
    """ক্রপ পপআপের নিশ্চিত বোতামে ক্লিক করে সেটি পুরোপুরি বন্ধ হওয়া পর্যন্ত অপেক্ষা করে"""
    try:
        page.wait_for_timeout(2000)
        # ক্রপ মোডালের ওকে/কনফার্ম বোতাম
        crop_ok = page.locator('.ant-modal:visible button:has-text("OK"), .ant-modal:visible button:has-text("Confirm"), .ant-modal:visible button.ant-btn-primary')
        if crop_ok.count() > 0:
            print("✓ Confirming image crop...", flush=True)
            crop_ok.first.click(force=True)
            page.wait_for_timeout(3000)
            
        # যদি ক্রপ মোডাল এখনো খোলা থাকে, ক্লোজ বাটন প্রেস করে বন্ধ করা
        close_x = page.locator('.ant-modal:visible .ant-modal-close')
        if close_x.count() > 0:
            close_x.first.click(force=True)
            page.wait_for_timeout(1500)
    except Exception as e:
        print(f"Crop modal note: {e}", flush=True)

# ============================================================
# LOGIN
# ============================================================

def login(page):
    print("Logging into Serey...", flush=True)
    page.goto(SEREY, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    dismiss_overlays(page)

    logged_in = page.locator(f'a[href*="/authors/{SEREY_LOGIN}"], button:has-text("Logout"), a:has-text("Logout")')
    if logged_in.count() > 0 and logged_in.first.is_visible():
        print("✓ Already logged in Serey.", flush=True)
        return

    login_buttons = page.locator('button:has-text("Log in"), a:has-text("Log in"), button:has-text("Log In"), a:has-text("Log In")')
    if login_buttons.count() > 0 and login_buttons.first.is_visible():
        login_buttons.first.click(timeout=10000)
        page.wait_for_timeout(3000)

    user_in = page.locator('input[placeholder*="Username" i], input[type="text"]').first
    pass_in = page.locator('input[placeholder*="Private Key" i], input[placeholder*="Password" i], input[type="password"]').first

    user_in.wait_for(state="visible", timeout=25000)
    pass_in.wait_for(state="visible", timeout=25000)

    user_in.fill(SEREY_LOGIN)
    pass_in.fill(SEREY_PASSWORD)

    submit = page.locator('.ant-modal button[type="submit"], button:has-text("Log in"), button:has-text("Log In")').last
    submit.click(force=True, timeout=15000)
    page.wait_for_timeout(7000)
    print("✓ Logged into Serey successfully!", flush=True)

# ============================================================
# PUBLISH
# ============================================================

def publish(page, post):
    print("-" * 60, flush=True)
    print(f"Publishing: {post['title']} (Steem Date: {post.get('created', 'N/A')})", flush=True)

    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    dismiss_overlays(page)

    # 1. Title
    title_box = page.locator('input[placeholder*="title" i], textarea[placeholder*="title" i]').first
    title_box.wait_for(state="visible", timeout=20000)
    title_box.fill(post["title"])
    print("✓ Title filled", flush=True)

    # 2. Body
    editor = page.locator('.ql-editor, div[contenteditable="true"]').first
    editor.wait_for(state="visible", timeout=20000)
    try:
        editor.fill(post["body"])
    except Exception:
        editor.click(force=True)
        page.keyboard.insert_text(post["body"])
    print(f"✓ Body filled ({len(post['body'])} characters)", flush=True)
    page.wait_for_timeout(1000)

    # 3. Image Upload
    downloaded_img = download_image(post.get("thumbnail"))
    if downloaded_img:
        try:
            file_inputs = page.locator('input[type="file"]')
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(downloaded_img)
                print("✓ Thumbnail uploaded.", flush=True)
                page.wait_for_timeout(4000)
                handle_crop_modal(page)
        except Exception as e:
            print(f"❌ Thumbnail upload failed: {e}", flush=True)

    dismiss_overlays(page)

    # 4. First Publish বাটন ক্লিক (এডিটরের নিচে থাকা বাটন)
    print("Attempting to click first Publish...", flush=True)
    first_publish_btn = None
    all_buttons = page.locator('button, a')
    for i in range(min(all_buttons.count(), 200)):
        el = all_buttons.nth(i)
        try:
            if el.is_visible() and el.inner_text().strip().lower() == "publish":
                first_publish_btn = el
                break
        except Exception:
            continue

    if not first_publish_btn:
        print("❌ First Publish button not found.", flush=True)
        return None

    first_publish_btn.scroll_into_view_if_needed()
    first_publish_btn.click(force=True)
    print("✓ First Publish clicked.", flush=True)
    page.wait_for_timeout(3000)

    # 5. Category সিলেকশন (Publish Modal-এর ভেতরে)
    try:
        select_box = page.locator('.ant-modal-wrap:visible .ant-select-selector').first
        select_box.wait_for(state="visible", timeout=10000)
        select_box.click(force=True)
        page.wait_for_timeout(1000)

        # প্রথম অপশনে ক্লিক করা
        opt = page.locator('.ant-select-dropdown:visible .ant-select-item-option').first
        if opt.is_visible():
            opt_name = opt.inner_text().strip()
            opt.click(force=True)
            print(f"✓ Category selected: {opt_name}", flush=True)
            page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Category selection note: {e}", flush=True)

    # 6. Final Publish বাটন ক্লিক (JS দিয়ে সরাসরি ক্লিক)
    dismiss_overlays(page)
    modal = page.locator(".ant-modal-wrap:visible").last
    final_btn = modal.locator('button:has-text("Publish"), button:has-text("Submit"), button.ant-btn-primary').last

    print("Triggering final Publish click...", flush=True)
    final_btn.evaluate("btn => { btn.disabled = false; btn.click(); }")
    page.wait_for_timeout(8000)

    # 7. পোস্ট সফল হয়েছে কিনা চেক
    if downloaded_img and os.path.exists(downloaded_img):
        try:
            os.remove(downloaded_img)
        except Exception:
            pass

    for sec in range(15):
        page.wait_for_timeout(1000)
        if "/blog/post/new" not in page.url or "authors" in page.url:
            print(f"✓ PUBLISHED SUCCESSFULLY! URL: {page.url}", flush=True)
            return page.url

    print("Checking if published via activity...", flush=True)
    return "published_done"

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("STEEM -> BENGALI SEREY AUTO SYNC")
    print("LAST 365 DAYS -> OLDEST TO NEWEST")
    print("=" * 60)

    if not STEEM_USERNAME or not SEREY_LOGIN or not SEREY_PASSWORD:
        print("❌ Missing Secrets!", flush=True)
        return

    synced = load_synced()
    print(f"Previously synced: {len(synced)}", flush=True)

    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced]
    print(f"Unsynced posts remaining: {len(new_posts)}", flush=True)

    if not new_posts:
        print("No new posts to publish.", flush=True)
        return

    post_to_run = new_posts[0]
    print(f"Selected: {post_to_run['id']}\nCreated: {post_to_run['created']}", flush=True)

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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            login(page)
            res = publish(page, post_to_run)
            if res:
                print(f"✓ SUCCESS: {post_to_run['id']}", flush=True)
                synced.add(post_to_run["id"])
                save_synced(synced)
            else:
                print(f"⚠ FAILED: {post_to_run['id']}", flush=True)
        finally:
            browser.close()

    print("\n" + "=" * 60 + "\nRUN FINISHED\n" + "=" * 60)

if __name__ == "__main__":
    main()
