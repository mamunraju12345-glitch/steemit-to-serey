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

# মেইন ডোমেইন ব্যবহার করা হচ্ছে
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
    # প্রথম ইমেজ লিঙ্কটি খুঁজে বের করা
    image_match = re.search(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)', body, re.I)
    image_url = image_match.group(0) if image_match else None
    
    # বডি থেকে সব ইমেজ লিঙ্ক এবং অপ্রয়োজনীয় মার্কডাউন সরানো
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

# ============================================================
# STEEM থেকে পোস্ট সংগ্রহ
# ============================================================

def get_steem_posts():
    print(f"Checking posts for @{STEEM_USERNAME}...", flush=True)
    payload = {
        "jsonrpc": "2.0",
        "method": "condenser_api.get_discussions_by_blog",
        "params": {"tag": STEEM_USERNAME, "limit": 20},
        "id": 1
    }
    try:
        r = requests.post(STEEM_NODES[0], json=payload, timeout=20)
        result = r.json().get("result", [])
        posts = []
        for p in result:
            if p.get("author") == STEEM_USERNAME:
                body, img = clean_post(p.get("body", ""))
                posts.append({
                    "id": f"{p['author']}/{p['permlink']}",
                    "title": p.get("title", ""),
                    "body": body,
                    "image": img
                })
        return posts
    except: return []

# ============================================================
# পাবলিশিং প্রসেস (স্ক্রিনশট অনুযায়ী)
# ============================================================

def publish_process(page, post):
    print(f"\n🚀 সিঙ্কিং শুরু: {post['title']}")
    
    try:
        # ১. নতুন পোস্ট পেজে যাওয়া (Timeout ও Wait সংশোধন করা হয়েছে)
        page.goto(NEW_POST_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        # ২. টাইটেল বসানো
        page.fill('input[placeholder*="Enter title"]', post['title'])
        print("✓ টাইটেল যুক্ত হয়েছে।")

        # ৩. কন্টেন্ট বসানো
        editor = page.locator('div[contenteditable="true"]').first
        editor.click()
        editor.fill(post['body'])
        print("✓ কন্টেন্ট যুক্ত হয়েছে।")

        # ৪. ইমেজ বা থাম্বনেইল আপলোড
        img_path = download_image(post['image'])
        if img_path:
            try:
                page.set_input_files('input[type="file"]', img_path)
                page.wait_for_timeout(6000) 
                print("✓ থাম্বনেইল আপলোড হয়েছে।")
            except:
                print("⚠️ থাম্বনেইল আপলোড করা যায়নি।")

        # ৫. প্রথমবার 'Publish' বাটনে ক্লিক (নীল বাটন)
        page.locator('button:has-text("Publish")').first.click(force=True)
        print("✓ প্রথমবার Publish ক্লিক করা হয়েছে। AI প্রসেসিং হচ্ছে...")

        # ৬. AI ক্যাটাগরি পপ-আপ হ্যান্ডলিং
        try:
            # পপ-আপে "Your post belongs to category" আসা পর্যন্ত অপেক্ষা
            page.wait_for_selector('text="Your post belongs to category"', timeout=30000)
            print("✓ AI ক্যাটাগরি পপ-আপ দেখা দিয়েছে।")
            
            # পপ-আপ এর ভেতরের নীল 'Publish' বাটনে ক্লিক করুন
            final_btn = page.locator('button:has-text("Publish")').last
            final_btn.click(force=True)
            print("✓ দ্বিতীয়বার (Final) Publish ক্লিক করা হয়েছে।")

            # ৭. সফলতার মেসেজ আসা পর্যন্ত অপেক্ষা
            page.wait_for_selector('text="Successfully posted your article"', timeout=40000)
            print("✅ পোস্ট সফলভাবে পাবলিশ হয়েছে!")
            return True

        except Exception as e:
            print(f"❌ পপ-আপ বা ফাইনাল পাবলিশ সমস্যা: {str(e)}")
            return False

    except Exception as e:
        print(f"❌ পাবলিশিং ব্যর্থ হয়েছে: {str(e)}")
        return False

# ============================================================
# মেইন ফাংশন
# ============================================================

def main():
    synced = load_synced()
    all_posts = get_steem_posts()
    
    to_sync = [p for p in all_posts if p['id'] not in synced][:POSTS_PER_RUN]
    
    if not to_sync:
        print("সিঙ্ক করার মতো কোনো নতুন পোস্ট নেই।")
        return

    with sync_playwright() as p:
        # ব্রাউজার লঞ্চ
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # শুরুতে একবার লগইন
        print("Serey-তে লগইন করা হচ্ছে...")
        try:
            # wait_until="domcontentloaded" ব্যবহার করা হয়েছে টাইম-আউট এড়াতে
            page.goto(SEREY, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)
            
            # লগইন বাটন ক্লিক
            login_btn = page.locator('text="Log in", text="Log In"').first
            if login_btn.is_visible():
                login_btn.click()
                page.wait_for_timeout(2000)
                page.fill('input[placeholder*="Username"]', SEREY_LOGIN)
                page.fill('input[placeholder*="Private Key"]', SEREY_PASSWORD)
                page.click('button:has-text("Log in"), button:has-text("Log In")')
                page.wait_for_timeout(6000)
                print("✓ লগইন সম্পন্ন হয়েছে।")
            else:
                print("⚠️ লগইন বাটন পাওয়া যায়নি, সম্ভবত আপনি অলরেডি লগইন আছেন।")
        except Exception as e:
            print(f"❌ লগইন প্রসেসে টাইম-আউট বা এরর: {str(e)}")
            # লগইন না হলেও সিঙ্ক চেষ্টা করতে পারি যদি সেশন থাকে

        # পোস্ট সিঙ্ক শুরু
        for post in to_sync:
            if publish_process(page, post):
                synced.add(post['id'])
                save_synced(synced)
        
        browser.close()
    
    # টেম্প ফাইল ডিলিট
    if os.path.exists(TEMP_IMAGE): os.remove(TEMP_IMAGE)

if __name__ == "__main__":
    main()
