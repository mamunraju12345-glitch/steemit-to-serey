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
# STEEM RPC & SYNC FILE
# ============================================================

def rpc(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    for node in STEEM_NODES:
        try:
            r = requests.post(node, json=payload, timeout=20)
            return r.json()["result"]
        except: continue
    raise Exception("All Steem RPC nodes failed")

def load_synced():
    if not os.path.exists(SYNC_FILE): return set()
    try:
        with open(SYNC_FILE, encoding="utf-8") as f: return set(json.load(f))
    except: return set()

def save_synced(data):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)

# ============================================================
# CLEAN BODY & IMAGE
# ============================================================

def clean_post(body, metadata):
    image = None
    try:
        meta = json.loads(metadata or "{}")
        for x in meta.get("image", []):
            if isinstance(x, str): image = x; break
    except: pass
    if not image:
        m = re.search(r'!\[[^\]]*\]\((https?://[^)\s]+)', body, re.I)
        if m: image = m.group(1)
    body = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', body)
    body = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?', '', body, flags=re.I)
    return body.strip(), image

def download_image(url):
    if not url: return None
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(TEMP_IMAGE, "wb") as f: f.write(r.content)
            return os.path.abspath(TEMP_IMAGE)
    except: return None

# ============================================================
# GET POSTS (Last 1 Year, Oldest First)
# ============================================================

def get_posts():
    print(f"Getting posts from last 1 year for @{STEEM_USERNAME}...", flush=True)
    posts, seen = [], set()
    one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
    start_author, start_permlink = None, None
    while len(posts) < 5000:
        params = {"tag": STEEM_USERNAME, "limit": 100}
        if start_author: params.update({"start_author": start_author, "start_permlink": start_permlink})
        result = rpc("condenser_api.get_discussions_by_blog", params)
        if not result: break
        batch = result[1:] if start_author else result
        old_detected = False
        for p in batch:
            dt = datetime.strptime(p['created'], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if dt < one_year_ago: old_detected = True; continue
            pid = f"{p['author']}/{p['permlink']}"
            if pid not in seen:
                seen.add(pid); b, img = clean_post(p.get("body", ""), p.get("json_metadata", "{}"))
                posts.append({"id": pid, "title": p.get("title", "").strip(), "body": b, "image": img, "created": dt})
        if old_detected or len(result) < 100: break
        start_author, start_permlink = result[-1]['author'], result[-1]['permlink']
        time.sleep(0.3)
    posts.sort(key=lambda x: x['created'])
    print(f"Total eligible posts: {len(posts)}", flush=True)
    return posts

# ============================================================
# PUBLISH (সংশোধিত শক্তিশালী লজিক)
# ============================================================

def publish(page, post):
    print("-" * 60); print(f"Publishing: {post['title']}", flush=True)
    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # ইনপুট ডাটা
    page.locator('input[placeholder*="Enter title"]').fill(post["title"])
    editor = page.locator('div[contenteditable="true"]').first
    editor.click(); editor.fill(post["body"])

    # ইমেজ আপলোড
    image = download_image(post.get("image"))
    if image:
        try:
            page.set_input_files('input[type="file"]', image)
            print("⌛ Waiting for thumbnail upload..."); page.wait_for_timeout(10000)
        except: pass

    # ১. প্রথমবার পাবলিশ বাটন ক্লিক
    page.locator('button:has-text("Publish")').last.click(force=True)
    print("✓ FIRST PUBLISH CLICKED. Processing Pop-up...", flush=True)
    
    page.wait_for_timeout(8000) # প্রসেসিং বিরতি

    try:
        # পপ-আপের বাটন খোঁজা (বিভিন্ন সিলেক্টর দিয়ে চেষ্টা)
        final_btn = page.locator('div[role="dialog"] button:has-text("Publish"), .modal-content button:has-text("Publish")').last
        
        if final_btn.is_visible(timeout=20000):
            print("✓ AI Pop-up detected. Clicking FINAL Publish...")
            final_btn.click(force=True)
        else:
            # যদি পপ-আপ না আসে, তবে ম্যানুয়ালি ক্যাটাগরি ও সাব-ক্যাটাগরি সিলেক্ট করা
            print("AI Pop-up not visible. Trying manual selectors...")
            if page.get_by_text("Select category").is_visible():
                page.get_by_text("Select category").first.click()
                page.wait_for_timeout(1000)
                page.locator('[role="option"]').first.click()
                print("✓ Category selected.")
                
                # সাব-ক্যাটাগরি চেক
                if page.get_by_text("Select sub category").is_visible():
                    page.get_by_text("Select sub category").first.click()
                    page.wait_for_timeout(1000)
                    page.locator('[role="option"]').first.click()
                    print("✓ Sub Category selected.")

            # সবশেষে পেজের নিচের পাবলিশ বাটন ক্লিক
            page.locator('button:has-text("Publish")').last.click(force=True)
            print("✓ Manual Final Publish clicked.")

        # পাবলিশ হওয়ার জন্য অপেক্ষা
        page.wait_for_timeout(15000)

        # ভেরিফিকেশন
        for _ in range(6):
            page.wait_for_timeout(5000)
            if "/authors/" in page.url and "/blog/post/new" not in page.url:
                print(f"✓ SUCCESS: {page.url}"); return True
            if page.locator('text="Successfully posted your article"').is_visible():
                print("✓ SUCCESS: Post confirmation visible."); return True

        # ব্যর্থ হলে ডিবাগ করার জন্য স্ক্রিনশট
        page.screenshot(path="publish_error.png")
        print("❌ Verification failed. Saved error screenshot."); return False

    except Exception as e:
        print(f"❌ Error during final steps: {e}"); return False

# ============================================================
# MAIN
# ============================================================

def main():
    synced = load_synced()
    posts = get_posts()
    to_sync = [p for p in posts if p["id"] not in synced][:POSTS_PER_RUN]
    if not to_sync: print("Nothing to publish."); return

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
            for post in to_sync:
                if publish(page, post):
                    synced.add(post["id"]); save_synced(synced)
        finally:
            if os.path.exists(TEMP_IMAGE): os.remove(TEMP_IMAGE)
            browser.close()

if __name__ == "__main__": main()
