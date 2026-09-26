import os
import json
import re
import time
import mimetypes
from datetime import datetime, timedelta, timezone

import requests
from playwright.sync_api import sync_playwright

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

def rpc(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    for node in STEEM_NODES:
        try:
            r = requests.post(node, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise Exception(data["error"])
            return data["result"]
        except Exception:
            pass
    raise Exception("All Steem RPC nodes failed")

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

def extract_thumbnail_and_body(body, metadata):
    thumbnail = None
    try:
        meta = json.loads(metadata or "{}")
        images = meta.get("image", [])
        if isinstance(images, list) and images:
            thumbnail = images[0]
    except Exception:
        pass

    if not thumbnail:
        m = re.search(r'!\[[^\]]*\]\((https?://[^)\s]+)', body, re.I)
        if m: thumbnail = m.group(1)
    if not thumbnail:
        m = re.search(r'<img[^>]+src=["\'](https?://[^"\'>\s]+)', body, re.I)
        if m: thumbnail = m.group(1)

    # Clean Markdown & HTML
    body = re.sub(r'!\[[^\]]*\]\(\s*https?://[^)\s]+\s*\)', '', body, flags=re.I)
    body = re.sub(r'<img\b[^>]*>', '', body, flags=re.I)
    body = re.sub(r'<[^>]+>', '', body)
    body = re.sub(r'^\s{0,3}#{1,6}\s*', '', body, flags=re.M)
    body = re.sub(r'\*\*(.*?)\*\*', r'\1', body, flags=re.S)
    body = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1', body, flags=re.I)

    lines = [l.strip() for l in body.splitlines() if l.strip() and not re.fullmatch(r'https?://\S+', l.strip(), re.I)]
    return "\n\n".join(lines).strip(), thumbnail

def get_posts():
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_LIMIT)
    posts, seen = [], set()
    start_author, start_permlink = None, None

    while len(posts) < 3000:
        params = {"tag": STEEM_USERNAME, "limit": 100}
        if start_author:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        res = rpc("condenser_api.get_discussions_by_blog", params)
        if not res: break
        batch = res[1:] if start_author else res
        if not batch: break

        for p in batch:
            if p.get("author") != STEEM_USERNAME: continue
            pid = f"{p['author']}/{p['permlink']}"
            if pid in seen: continue
            created = datetime.strptime(p["created"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if created < cutoff: return posts

            seen.add(pid)
            clean_b, thumb = extract_thumbnail_and_body(p.get("body", ""), p.get("json_metadata", "{}"))
            posts.append({
                "id": pid,
                "title": p.get("title", "").strip(),
                "body": clean_b,
                "thumbnail": thumb,
                "created": p["created"]
            })

        if res[-1]["author"] == start_author and res[-1]["permlink"] == start_permlink:
            break
        start_author, start_permlink = res[-1]["author"], res[-1]["permlink"]
        time.sleep(0.2)

    posts.reverse()
    return posts

def download_image(url):
    if not url: return None
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ext = mimetypes.guess_extension(r.headers.get("content-type", "").split(";")[0]) or ".jpg"
        fp = f"{TEMP_IMAGE_PREFIX}{ext}"
        with open(fp, "wb") as f: f.write(r.content)
        return fp
    except Exception:
        return None

def clear_overlays(page):
    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.no-cookie-notice-overlay, [class*="cookie"]').forEach(e => e.remove());
            }
        """)
    except Exception:
        pass

def login(page):
    print("Logging into Serey...", flush=True)
    page.goto(SEREY, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    clear_overlays(page)

    if page.locator(f'a[href*="/authors/{SEREY_LOGIN}"], button:has-text("Logout")').count() > 0:
        print("✓ Already logged in.", flush=True)
        return

    btn = page.locator('button:has-text("Log in"), a:has-text("Log in"), button:has-text("Log In")').first
    if btn.is_visible():
        btn.click()
        page.wait_for_timeout(2000)

    page.locator('input[placeholder*="Username" i], input[type="text"]').first.fill(SEREY_LOGIN)
    page.locator('input[placeholder*="Private Key" i], input[placeholder*="Password" i], input[type="password"]').first.fill(SEREY_PASSWORD)
    page.locator('.ant-modal button[type="submit"], button:has-text("Log in")').last.click(force=True)
    page.wait_for_timeout(6000)
    print("✓ Logged in.", flush=True)

def publish(page, post):
    print(f"Publishing: {post['title']}", flush=True)
    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    clear_overlays(page)

    # 1. Title
    title_box = page.locator('input[placeholder*="title" i], textarea[placeholder*="title" i]').first
    title_box.wait_for(state="visible", timeout=15000)
    title_box.fill(post["title"])

    # 2. Body
    editor = page.locator('.ql-editor, div[contenteditable="true"]').first
    editor.wait_for(state="visible", timeout=15000)
    try:
        editor.fill(post["body"])
    except Exception:
        editor.click()
        page.keyboard.insert_text(post["body"])
    page.wait_for_timeout(1000)

    # 3. Image
    img = download_image(post.get("thumbnail"))
    if img:
        try:
            fi = page.locator('input[type="file"]')
            if fi.count() > 0:
                fi.first.set_input_files(img)
                page.wait_for_timeout(4000)
                # Crop confirm
                crop_ok = page.locator('.ant-modal:visible button:has-text("OK"), .ant-modal:visible button:has-text("Confirm")').first
                if crop_ok.is_visible():
                    crop_ok.click(force=True)
                    page.wait_for_timeout(2000)
        except Exception:
            pass

    clear_overlays(page)

    # 4. Click Publish (Main Editor Screen)
    print("Clicking editor Publish button...", flush=True)
    pub_btn = page.locator('button:has-text("Publish"), a:has-text("Publish")').first
    pub_btn.scroll_into_view_if_needed()
    pub_btn.click(force=True)
    page.wait_for_timeout(3000)

    # 5. Select Category (Select box anywhere on modal or page)
    print("Selecting category...", flush=True)
    try:
        select_box = page.locator('.ant-modal:visible .ant-select, .ant-select-selector:visible').first
        if select_box.is_visible():
            select_box.click(force=True)
            page.wait_for_timeout(1000)
            opt = page.locator('.ant-select-dropdown:visible .ant-select-item-option').first
            if opt.is_visible():
                opt.click(force=True)
                print(f"✓ Category selected: {opt.inner_text().strip()}", flush=True)
                page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Category selection error: {e}", flush=True)

    # 6. Click Final Publish
    clear_overlays(page)
    modal = page.locator('.ant-modal:visible').last
    if modal.is_visible():
        final_btn = modal.locator('button:has-text("Publish"), button:has-text("Submit"), button.ant-btn-primary').last
    else:
        final_btn = page.locator('button:has-text("Publish"), button:has-text("Submit")').last

    print("Triggering final submission...", flush=True)
    final_btn.evaluate("btn => { btn.disabled = false; btn.click(); }")

    # 7. কঠোর সত্যতা যাচাই (Strict Verification)
    # URL পরিবর্তন হয়েছে কি না বা নতুন পোস্ট তৈরি হয়েছে কি না নিশ্চিত করা
    print("Awaiting post redirection...", flush=True)
    for _ in range(20):
        page.wait_for_timeout(1000)
        curr = page.url.lower()
        if "/blog/post/new" not in curr and ("authors" in curr or "blog" in curr):
            print(f"✓ REAL SUCCESS! Published URL: {page.url}", flush=True)
            if img and os.path.exists(img): os.remove(img)
            return page.url

    # যদি ২০ সেকেন্ডেও পেজ পরিবর্তন না হয়, তার মানে পোস্ট ফেইল করেছে!
    print("❌ Post did not submit! Taking error screenshot...", flush=True)
    page.screenshot(path="post_failed.png", full_page=True)
    if img and os.path.exists(img): os.remove(img)
    return None  # কোনো ফেক সাকসেস দেওয়া হবে না!

def main():
    if not STEEM_USERNAME or not SEREY_LOGIN or not SEREY_PASSWORD:
        print("❌ Missing Secrets!", flush=True)
        return

    synced = load_synced()
    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced]

    if not new_posts:
        print("No new posts to publish.", flush=True)
        return

    post_to_run = new_posts[0]
    print(f"Target Post: {post_to_run['id']}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
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
                print(f"✓✓✓ SUCCESSFULLY SYNCED: {post_to_run['id']} ✓✓✓", flush=True)
                synced.add(post_to_run["id"])
                save_synced(synced)
            else:
                print(f"❌ POST FAILED: {post_to_run['id']} (NOT SAVED TO JSON)", flush=True)
                raise Exception("Publish verification failed! Page did not redirect.")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
