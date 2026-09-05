import os
import json
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_LOGIN = os.environ.get("SEREY_USERNAME", "").replace("@", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY = "https://serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"
POSTS_PER_RUN = 1

STEEM_NODES = ["https://api.steemit.com", "https://api.justyy.com"]

# ============================================================
# ডাটাবেজ ফাংশন
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE): return set()
    try:
        with open(SYNC_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except: return set()

def save_synced(data):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)

# ============================================================
# কন্টেন্ট ও ইমেজ হ্যান্ডলিং
# ============================================================

def clean_post(body, metadata):
    image = None
    try:
        meta = json.loads(metadata or "{}")
        for x in meta.get("image", []):
            if isinstance(x, str):
                image = x
                break
    except: pass
    if not image:
        m = re.search(r'!\[[^\]]*\]\((https?://[^)\s]+)', body, re.I)
        if m: image = m.group(1)

    body = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', body)
    body = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?', '', body, flags=re.I)
    body = re.sub(r'\n{3,}', '\n\n', body)
    return body.strip(), image

def download_image(url):
    if not url: return None
    try:
        print(f"Downloading image: {url}", flush=True)
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(TEMP_IMAGE, "wb") as f:
                f.write(r.content)
            return os.path.abspath(TEMP_IMAGE)
    except Exception as e:
        print(f"Image download failed: {e}")
    return None

# ============================================================
# ১ বছরের পোস্ট সংগ্রহ (পুরাতন থেকে নতুন)
# ============================================================

def get_posts():
    print(f"Getting posts from last 1 year for @{STEEM_USERNAME}...", flush=True)
    posts = []
    seen = set()
    one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
    
    start_author = None
    start_permlink = None
    
    while True:
        payload = {
            "jsonrpc": "2.0", "method": "condenser_api.get_discussions_by_blog",
            "params": {"tag": STEEM_USERNAME, "limit": 50, "start_author": start_author, "start_permlink": start_permlink} if start_author else {"tag": STEEM_USERNAME, "limit": 50},
            "id": 1
        }
        r = requests.post("https://api.steemit.com", json=payload, timeout=20)
        result = r.json().get("result", [])
        if not result: break
        
        batch = result[1:] if start_author else result
        if not batch: break

        old_post_detected = False
        for p in batch:
            created_dt = datetime.strptime(p['created'], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            
            # ১ বছরের বেশি পুরনো হলে লুপ থামিয়ে দাও
            if created_dt < one_year_ago:
                old_post_detected = True
                continue
            
            pid = f"{p['author']}/{p['permlink']}"
            if pid not in seen:
                seen.add(pid)
                body, img = clean_post(p.get("body", ""), p.get("json_metadata", "{}"))
                posts.append({"id": pid, "title": p.get("title", ""), "body": body, "image": img, "created": created_dt})

        if old_post_detected or len(result) < 50: break
        start_author, start_permlink = result[-1]['author'], result[-1]['permlink']
        time.sleep(0.3)

    # পুরাতন পোস্ট আগে পাবলিশ করার জন্য সাজানো (Oldest First)
    posts.sort(key=lambda x: x['created'])
    print(f"Total eligible posts (last 1 year): {len(posts)}", flush=True)
    return posts

# ============================================================
# পাবলিশিং প্রসেস (থাম্বনেইল ফিক্স সহ)
# ============================================================

def publish(page, post):
    print("-" * 60)
    print(f"Publishing: {post['title']}", flush=True)
    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # টাইটেল ও বর্ণনা
    page.locator('input[placeholder*="Enter title"]').fill(post["title"])
    editor = page.locator('div[contenteditable="true"]').first
    editor.click()
    editor.fill(post["body"])

    # ইমেজ আপলোড (উন্নত করা হয়েছে)
    image = download_image(post.get("image"))
    if image:
        try:
            page.set_input_files('input[type="file"]', image)
            print("⌛ Waiting for image upload to complete...")
            page.wait_for_timeout(10000) # আপলোডের জন্য পর্যাপ্ত সময়
            print("✓ Thumbnail uploaded")
        except Exception as e:
            print(f"Thumbnail upload failed: {e}")

    # প্রথমবার পাবলিশ বাটন
    page.get_by_text("Publish", exact=True).last.click(force=True)
    print("✓ FIRST PUBLISH CLICKED. Waiting for AI Pop-up...")

    # AI পপ-আপ হ্যান্ডলিং
    try:
        final_btn = page.locator('div[role="dialog"] button:has-text("Publish"), .modal-content button:has-text("Publish")').last
        final_btn.wait_for(state="visible", timeout=60000)
        final_btn.click(force=True)
        print("✓ FINAL PUBLISH CLICKED.")
        page.wait_for_timeout(15000)
    except Exception as e:
        print(f"❌ Pop-up handling failed: {e}")
        return False

    # ভেরিফিকেশন
    for _ in range(5):
        page.wait_for_timeout(6000)
        if "/authors/" in page.url and "/blog/post/new" not in page.url:
            print(f"✓ SUCCESS: {page.url}")
            return True
    return False

# ============================================================
# মেইন ফাংশন
# ============================================================

def main():
    synced = load_synced()
    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced]
    
    posts_to_run = new_posts[:POSTS_PER_RUN]
    if not posts_to_run:
        print("Nothing to publish.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900}, user_agent="Mozilla/5.0")
        page = context.new_page()

        try:
            # লগইন
            page.goto(SEREY, wait_until="domcontentloaded", timeout=60000)
            page.click('text="Log in", text="Log In"', timeout=15000)
            page.fill('input[placeholder*="Username"]', SEREY_LOGIN)
            page.fill('input[placeholder*="Private Key"]', SEREY_PASSWORD)
            page.click('button:has-text("Log in"), button:has-text("Log In")')
            page.wait_for_timeout(8000)

            for post in posts_to_run:
                if publish(page, post):
                    synced.add(post["id"])
                    save_synced(synced)
                    print(f"✓ SAVED: {post['id']}")
        finally:
            if os.path.exists(TEMP_IMAGE): os.remove(TEMP_IMAGE)
            browser.close()

if __name__ == "__main__":
    main()
