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

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

# আপনার স্ক্রিনশট অনুযায়ী মেইন ডোমেইন
SEREY = "https://serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"

POSTS_PER_RUN = 1

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
            if "error" in data: continue
            return data["result"]
        except: continue
    raise Exception("All Steem RPC nodes failed")


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE): return set()
    try:
        with open(SYNC_FILE, encoding="utf-8") as f: return set(json.load(f))
    except: return set()


def save_synced(data):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)


# ============================================================
# CLEAN BODY + IMAGE
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
    body = re.sub(r'\n{3,}', '\n\n', body)
    return body.strip(), image


# ============================================================
# GET STEEM POSTS (গত ১ বছর)
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
        if not batch: break

        old_post_found = False
        for p in batch:
            created_dt = datetime.strptime(p['created'], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if created_dt < one_year_ago: old_post_found = True; continue
            if p.get("author") != STEEM_USERNAME: continue
            pid = f"{p['author']}/{p['permlink']}"
            if pid not in seen:
                seen.add(pid); body, image = clean_post(p.get("body", ""), p.get("json_metadata", "{}"))
                posts.append({"id": pid, "title": p.get("title", "").strip(), "body": body, "image": image, "created": created_dt})
        
        if old_post_found: break
        start_author, start_permlink = result[-1]['author'], result[-1]['permlink']
        time.sleep(0.3)

    posts.sort(key=lambda x: x['created']) # পুরনো আগে
    print(f"Total eligible posts: {len(posts)}", flush=True)
    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):
    if not url: return None
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(TEMP_IMAGE, "wb") as f: f.write(r.content)
            return os.path.abspath(TEMP_IMAGE)
    except: return None


# ============================================================
# LOGIN
# ============================================================

def login(page):
    print("Logging into Serey...", flush=True)
    page.goto(SEREY, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    login_btn = page.locator('a:has-text("Log in"), button:has-text("Log in"), a:has-text("Log In"), button:has-text("Log In")').first
    login_btn.wait_for(state="visible", timeout=30000)
    login_btn.click(force=True)
    page.wait_for_timeout(3000)
    page.locator('input[placeholder*="Username"]').first.fill(SEREY_LOGIN)
    page.locator('input[placeholder*="Private Key"]').first.fill(SEREY_PASSWORD)
    page.locator('button:has-text("Log in"), button:has-text("Log In")').last.click(force=True)
    page.wait_for_timeout(8000)
    print("✓ LOGGED INTO SEREY SUCCESSFULLY!", flush=True)


# ============================================================
# VERIFY
# ============================================================

def verify(page, title):
    print("VERIFYING PUBLISHED POST...", flush=True)
    for _ in range(6):
        page.wait_for_timeout(6000)
        if "/authors/" in page.url and "/blog/post/new" not in page.url:
            print(f"✓ SUCCESS: {page.url}"); return True
        if page.locator('text="Successfully posted your article"').is_visible():
            print("✓ SUCCESS: Post message detected."); return True
    return False


# ============================================================
# PUBLISH (সংশোধিত শক্তিশালী লজিক)
# ============================================================

def publish(page, post):
    print("-" * 60)
    print(f"Publishing: {post['title']}", flush=True)
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
    print("✓ FIRST PUBLISH CLICKED. Processing...", flush=True)
    
    # ২. পপ-আপ বা ম্যানুয়াল সিলেকশনের জন্য অপেক্ষা
    page.wait_for_timeout(8000)
    
    success_final_click = False
    for i in range(10): # মোট ৮০ সেকেন্ড অপেক্ষা করবে
        # পপ-আপ বাটন চেক
        final_btn = page.locator('div[role="dialog"] button:has-text("Publish"), .modal-content button:has-text("Publish")').last
        if final_btn.is_visible():
            print("✓ AI Pop-up detected. Clicking FINAL Publish...")
            final_btn.click(force=True)
            success_final_click = True
            break
        
        # ম্যানুয়াল ক্যাটাগরি চেক
        manual_cat = page.get_by_text("Select category").first
        if manual_cat.is_visible():
            print("Pop-up not found. Selecting manual category...")
            manual_cat.click()
            page.wait_for_timeout(1000)
            page.locator('[role="option"]').first.click()
            page.wait_for_timeout(2000)
            page.locator('button:has-text("Publish")').last.click(force=True)
            print("✓ Manual Final Publish clicked.")
            success_final_click = True
            break
        
        page.wait_for_timeout(8000)
        print(f"Waiting... attempt {i+1}/10")

    if not success_final_click:
        print("❌ Final steps failed. Saving debug screenshot.")
        page.screenshot(path="error_debug.png")
        return False

    page.wait_for_timeout(15000)
    return verify(page, post["title"])


# ============================================================
# MAIN
# ============================================================

def main():
    synced = load_synced()
    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced][:POSTS_PER_RUN]
    if not new_posts: print("Nothing to publish."); return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900}, user_agent="Mozilla/5.0")
        page = context.new_page()
        try:
            login(page)
            for post in new_posts:
                if publish(page, post):
                    synced.add(post["id"]); save_synced(synced)
                    print(f"✓ SAVED: {post['id']}")
                else: print("⚠️ NOT SAVED.")
        finally:
            if os.path.exists(TEMP_IMAGE): os.remove(TEMP_IMAGE)
            browser.close()

if __name__ == "__main__":
    main()
