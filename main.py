import os
import json
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# ============================================================
# কনফিগারেশন (Settings)
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_LOGIN = os.environ.get("SEREY_USERNAME", "").replace("@", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY = "https://serey.io"
NEW_POST_URL = f"{SEREY}/blog/post/new"

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

def clean_post(body):
    image_match = re.search(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)', body, re.I)
    image_url = image_match.group(0) if image_match else None
    clean_body = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', body)
    clean_body = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?', '', clean_body, flags=re.I)
    return clean_body.strip(), image_url

def download_image(url):
    if not url: return None
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(TEMP_IMAGE, "wb") as f:
                f.write(r.content)
            return os.path.abspath(TEMP_IMAGE)
    except: pass
    return None

def get_steem_posts():
    print(f"Checking posts for @{STEEM_USERNAME}...", flush=True)
    payload = {"jsonrpc": "2.0", "method": "condenser_api.get_discussions_by_blog", "params": {"tag": STEEM_USERNAME, "limit": 20}, "id": 1}
    try:
        r = requests.post(STEEM_NODES[0], json=payload, timeout=20)
        result = r.json().get("result", [])
        posts = []
        for p in result:
            if p.get("author") == STEEM_USERNAME:
                body, img = clean_post(p.get("body", ""))
                posts.append({"id": f"{p['author']}/{p['permlink']}", "title": p.get("title", ""), "body": body, "image": img})
        return posts
    except: return []

# ============================================================
# পাবলিশিং প্রসেস (স্মার্টার মোড)
# ============================================================

def publish_process(page, post):
    print(f"\n🚀 সিঙ্কিং শুরু: {post['title']}")
    
    try:
        page.goto(NEW_POST_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        # টাইটেল ও কন্টেন্ট পূরণ
        page.fill('input[placeholder*="Enter title"]', post['title'])
        editor = page.locator('div[contenteditable="true"]').first
        editor.click()
        editor.fill(post['body'])
        print("✓ টাইটেল ও কন্টেন্ট যুক্ত হয়েছে।")

        # ইমেজ আপলোড
        img_path = download_image(post['image'])
        if img_path:
            try:
                page.set_input_files('input[type="file"]', img_path)
                page.wait_for_timeout(6000)
                print("✓ থাম্বনেইল আপলোড হয়েছে।")
            except: pass

        # প্রথম পাবলিশ বাটন ক্লিক
        print("✓ প্রথমবার Publish ক্লিক করা হচ্ছে...")
        page.locator('button:has-text("Publish")').first.click(force=True)
        
        # পপ-আপের জন্য বিশেষ অপেক্ষা (AI Modal)
        print("⌛ ক্যাটাগরি পপ-আপের জন্য অপেক্ষা করছি (১ মিনিট পর্যন্ত)...")
        
        # এখানে আমরা শুধু টেক্সট নয়, বরং একটি নতুন ডায়ালগ বা পপ-আপ বাটন আসার জন্য অপেক্ষা করব
        try:
            # পপ-আপে সাধারণত একটি 'Publish' বাটন থাকে যা আগের বাটন থেকে আলাদা
            # আমরা ১ মিনিট পর্যন্ত অপেক্ষা করব
            page.wait_for_timeout(10000) # প্রসেসিংয়ের জন্য ১০ সেকেন্ড সময় দিন
            
            # আপনার স্ক্রিনশটে থাকা পপ-আপের পাবলিশ বাটনটি খুঁজি
            # এটি সাধারণত পপ-আপের ভেতরের বাটন হয়
            final_btn = page.locator('div[role="dialog"] button:has-text("Publish"), .modal-content button:has-text("Publish"), button:has-text("Publish")').last
            
            if final_btn.is_visible(timeout=50000):
                print("✓ ক্যাটাগরি পপ-আপ/বাটন পাওয়া গেছে।")
                final_btn.click(force=True)
                print("✓ ফাইনাল Publish ক্লিক করা হয়েছে।")
                
                # সফলতার মেসেজ
                page.wait_for_selector('text="Successfully posted your article"', timeout=40000)
                print("✅ পোস্ট সফলভাবে পাবলিশ হয়েছে!")
                return True
            else:
                print("❌ ১ মিনিটের মধ্যেও ফাইনাল পাবলিশ বাটন দেখা যায়নি।")
                return False

        except Exception as e:
            print(f"❌ পপ-আপ হ্যান্ডলিং সমস্যা: {str(e)}")
            return False

    except Exception as e:
        print(f"❌ পাবলিশিং ব্যর্থ: {str(e)}")
        return False

# ============================================================
# মেইন ফাংশন
# ============================================================

def main():
    synced = load_synced()
    all_posts = get_steem_posts()
    to_sync = [p for p in all_posts if p['id'] not in synced][:POSTS_PER_RUN]
    
    if not to_sync:
        print("নতুন কোনো পোস্ট নেই।")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        page = context.new_page()

        print("Serey-তে লগইন করা হচ্ছে...")
        try:
            page.goto(SEREY, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)
            
            # ইউজারনেম ইনপুট দিয়ে চেক করা (যদি লগইন না থাকে)
            if page.locator('text="Log in", text="Log In"').first.is_visible():
                page.click('text="Log in", text="Log In"', timeout=10000)
                page.fill('input[placeholder*="Username"]', SEREY_LOGIN)
                page.fill('input[placeholder*="Private Key"]', SEREY_PASSWORD)
                page.click('button:has-text("Log in"), button:has-text("Log In")')
                page.wait_for_timeout(8000)
                print("✓ লগইন সফল।")
            else:
                print("✓ অলরেডি লগইন অবস্থায় আছে।")
        except: pass

        for post in to_sync:
            if publish_process(page, post):
                synced.add(post['id'])
                save_synced(synced)
        
        browser.close()
    if os.path.exists(TEMP_IMAGE): os.remove(TEMP_IMAGE)

if __name__ == "__main__":
    main()
