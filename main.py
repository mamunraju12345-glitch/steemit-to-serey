import os
import json
import re
import time
import requests
from datetimeYour post belongs to category: Society"** পপ-আপটি দেখেছেন, আপনার বর্তমান কোড সেটি হ্যান্ডেল করতে পারছে** তৈরি করে দিয়েছি। এটি আপনার দেখানো প্রতিটি ধাপ (টাইটেল, ডেসক্রিপশন, ইমেজ আপলোড, এবং সেই বিশেষ পপ-আপ) নিখুঁতভাবে সম্পন্ন করবে।

নিচের কোডটি কপি করে আপনার `main.py` ফাইলে আপডেট করুন:

```python
import os
import json
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_play import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# ============================================================
# সেটিংস (আপনার স্ক্রিনশট অনুযায়ী আপডেট করা হয়েছে)
# ============================================================

STEEM না। কোডটি প্রথম 'Publish' বাটনে ক্লিক করেই ভাবছে কাজ শেষ, কিন্তু আসলে দ্বিতীয় পপ-আপের নীলwright

# ============================================================
# কনফিগারেশন (আপনার সিক্রেট থেকে আসবে)
# =================================_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_LOGIN = os.environ.get("SEREY_USERNAME", "").replace("@", "").strip()
SEREY_PASSWORD = os.environ.get("SER===========================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_LOGIN = osEY_PASSWORD", "").strip()

# ডোমেইন সংশোধন: bengali.serey.io এর বদলে serey.io ব্যবহার.environ.get("SEREY_USERNAME", "").replace("@", "").strip()
SEREY_PASSWORD = os 'Publish' বাটনে ক্লিক না করা পর্যন্ত পোস্ট পাবলিশ হয় না।

আপনার সব স্ক্রিনশট এবং প্রসেস অনুযায়ী আমি করছি
SEREY = "https://serey.io"
NEW_POST_URL = f"{SEREY.environ.get("SEREY_PASSWORD", "").strip()

# আপনার স্ক্রিনশট অনুযায়ী মেইন ডোমেইন ব্যবহার করা}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE হচ্ছে
SEREY = "https://serey.io"
NEW_POST_URL = f"{SEREY কোডটি একদম নিখুঁত করে দিচ্ছি। এই কোডটি আপনার ম্যানুয়াল প্রসেস (টাইটেল -> = "temp_image.jpg"
POSTS_PER_RUN = 1

STEEM_NODES}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = " = ["https://api.steemit.com", "https://api.justyy.com"]

# ================================= ডেসক্রিপশন -> ইমেজ -> ২ বার পাবলিশ ক্লিক) হুবহু অনুসরণ করবে।

### একদম ফাইনাল পাইtemp_image.jpg"
POSTS_PER_RUN = 1 

STEEM_NODES = ["===========================
# ডাটাবেজ এবং ইমেজ ক্লিনিং
# ============================================================

def load_synced():
থন কোড (সংশোধিত):

```python
import os
import json
import re
import time
import requests
fromhttps://api.steemit.com", "https://api.justyy.com"]

# ============================================================
    if not os.path.exists(SYNC_FILE): return set()
    try:
        with open(SYNC_ datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# =================================# ডাটাবেজ ফাংশন
# ============================================================

def load_synced():
    FILE, encoding="utf-8") as f:
            return set(json.load(f))
    ===========================
# সেটিংস (Settings)
# ============================================================

STEEM_USERNAME = os.environ["if not os.path.exists(SYNC_FILE): return set()
    try:
        with open(except: return set()

def save_synced(data):
    with open(SYNC_FILE, "STEEM_USERNAME"]
SEREY_LOGIN = os.environ.get("SEREY_USERNAME", "").replaceSYNC_FILE, encoding="utf-8") as f:
            return set(json.load(f))w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure("@", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip
    except: return set()

def save_synced(data):
    with open(SYNC_FILE_ascii=False, indent=2)

def clean_post(body):
    image_match = re.search(r()

# আপনার স্ক্রিনশট অনুযায়ী মেইন ডোমেইন
SEREY = "https://serey.io"
NEW_POST_URL = f"{SEREY}/blog/post/new"

SYNC_FILE = "syn, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f'https?://\S+\.(?:jpg|jpeg|png|gif|webp)', body, re.I)
    image_url = image_match.group(0) if image_match else None
    clean, ensure_ascii=False, indent=2)

# ============================================================
# ইমেজ ও কন্টেন্ট প্রced_posts.json"
TEMP_IMAGE = "temp_image.jpg"
POSTS_PER__body = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gifসেসিং
# ============================================================

def clean_post(body):
    # ইমেজ লিঙ্ক খোঁজা
    image_matchRUN = 1 

STEEM_NODES = ["https://api.steemit.com", "https://api.justyy|webp)(?:\?\S*)?', '', body, flags=re.I)
    clean_body = = re.search(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp.com"]

# ============================================================
# ডাটাবেজ ফাংশন
# ============================================================

def load re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean_body)
    return clean_body.strip(), image_url

def download_image(url):
    if not url: return)', body, re.I)
    image_url = image_match.group(0) if image_match else None
    
    # টেক্সট থেকে ইমেজ লিঙ্ক ও মার্কডাউন পরিষ্কার করা
    clean_body_synced():
    if not os.path.exists(SYNC_FILE): return set()
    try None
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": = re.sub(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp:
        with open(SYNC_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except: return set()

def save_synced(data):
     "Mozilla/5.0"})
        if r.status_code == 200:
            with open(TEMP_IMAGE, "wb") as f:
                f.write(r.content)
            return os.path.abspath(TEMP_IMAGE)
    except: pass
    return None

# =================)(?:\?\S*)?', '', body, flags=re.I)
    clean_body = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean_body)
    return clean_with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)

# =======================================================================================================
# STEEM থেকে পোস্ট সংগ্রহ
# ============================================================

def get_steem_posts():
    body.strip(), image_url

def download_image(url):
    if not url: return None
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent":
# ক্লিন টেক্সট ও ইমেজ হ্যান্ডলিং
# ============================================================

def clean_post(body):
     "Mozilla/5.0"})
        if r.status_code == 200:
            with# ইমেজ ইউআরএল খুঁজে বের করা
    image_match = re.search(r'https?://\print(f"Checking posts for @{STEEM_USERNAME}...", flush=True)
    payload = { open(TEMP_IMAGE, "wb") as f:
                f.write(r.content)
            S+\.(?:jpg|jpeg|png|gif|webp)', body, re.I)
    image_
        "jsonrpc": "2.0", "method": "condenser_api.get_discussionsreturn os.path.abspath(TEMP_IMAGE)
    except: return None

# ============================================================url = image_match.group(0) if image_match else None
    
    # বডি থেকে_by_blog",
        "params": {"tag": STEEM_USERNAME, "limit": 20
# STEEM থেকে পোস্ট সংগ্রহ
# ============================================================

def get_steem_posts():
     সব লিগ্যাসি ইমেজ কোড সরানো
    clean_body = re.sub(r'!\[[^\]]*\]\}, "id": 1
    }
    try:
        r = requests.post(STEEM_NODES[0], json=payload, timeout=20)
        result = r.json().get("print(f"@{STEEM_USERNAME} থেকে পোস্ট চেক করা হচ্ছে...")
    payload = {
        "jsonrpcresult", [])
        posts = []
        for p in result:
            if p.get("author")([^)]+\)', '', body)
    clean_body = re.sub(r'https?://\S": "2.0",
        "method": "condenser_api.get_discussions_by_ == STEEM_USERNAME:
                body, img = clean_post(p.get("body", ""))
+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?', '', clean_body,blog",
        "params": {"tag": STEEM_USERNAME, "limit": 20},
                        posts.append({
                    "id": f"{p['author']}/{p['permlink']}",
                    "title": p.get("title", ""),
                    "body": body,
                    "image": flags=re.I)
    
    return clean_body.strip(), image_url

def download_image(url"id": 1
    }
    try:
        r = requests.post(STEEM_NODES[0], json=payload, timeout=20)
        result = r.json().get("result", []) img
                })
        return posts
    except: return []

# ============================================================
# আপনার):
    if not url: return None
    try:
        r = requests.get(url, timeout=15
        posts = []
        for p in result:
            if p.get("author") == STEEM_USERNAME:
                body, img = clean_post(p.get("body", ""))
                posts. ম্যানুয়াল প্রসেস অনুযায়ী পাবলিশিং ফাংশন
# ============================================================

def publish_process, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(TEMP_IMAGE, "wb") as f:
                f.write(append({
                    "id": f"{p['author']}/{p['permlink']}",
                    "(page, post):
    print(f"\n--- সিঙ্ক শুরু: {post['title']} ---", flush=True)

    # ১. নতুন পোস্ট পেজে সরাসরি যাওয়া
    page.goto(NEW_POST_URLr.content)
            return os.path.abspath(TEMP_IMAGE)
    except: pass
    title": p.get("title", ""),
                    "body": body,
                    "image": img
                , wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(4return None

# ============================================================
# STEEM থেকে পোস্ট সংগ্রহ
# ============================================================

def get_ste})
        return posts
    except: return []

# ============================================================
# মূল পাবলিশিং প্রসেস000)

    # ২. টাইটেল ইনপুট
    page.fill('input[placeholder*em_posts():
    print(f"Checking posts for @{STEEM_USERNAME}...")
    payload = (আপনার স্ক্রিনশট অনুযায়ী সংশোধিত)
# ============================================================

def publish_process(page, post):
="Enter title"]', post['title'])
    print("✓ টাইটেল বসানো হয়েছে।", flush=True)

     {
        "jsonrpc": "2.0",
        "method": "condenser_api.get    print(f"\n[+] শুরু হচ্ছে: {post['title']}")

    try:
        # ১. লগইন ধাপ
        page.goto(SEREY, wait_until="domcontentloaded")
        page.wait_for_timeout(2# ৩. ডেসক্রিপশন (এডিটর) ইনপুট
    editor = page.locator('div[contenteditable_discussions_by_blog",
        "params": {"tag": STEEM_USERNAME, "limit": 20},
        "id": 1
    }
    try:
        r = requests.000)
        
        # লগইন বাটন ক্লিক
        login_btn = page.locator('text="="true"]').first
    editor.click()
    editor.fill(post['body'])
    print("✓ বর্ণনা বসানো হয়েছে।", flush=True)

    # ৪. ইমেজ বা থাম্বনেইল আপলোডpost(STEEM_NODES[0], json=payload, timeout=20)
        result = r.json().get("result", [])
        posts = []
        for p in result:
            if pLog in", text="Log In"').first
        if login_btn.is_visible():
            login_btn.click()
            page.fill('input[placeholder*="Username"]', SEREY_LOGIN)
            page.fill
    img_path = download_image(post['image'])
    if img_path:
        try:
            page.set_input_files('input[type="file"]', img_path)
            .get("author") == STEEM_USERNAME:
                body, img = clean_post(p.get("body", ""))
                posts.append({
                    "id": f"{p['author']}/{p['('input[placeholder*="Private Key"]', SEREY_PASSWORD)
            page.click('button:haspage.wait_for_timeout(5000)
            print("✓ থাম্বনেইল আপলোড হয়েছে।",permlink']}",
                    "title": p.get("title", ""),
                    "body": body,-text("Log in"), button:has-text("Log In")')
            page.wait_for_ flush=True)
        except: print("! ইমেজ আপলোড করা যায়নি।", flush=True)

    # ৫. প্রথমবার
                    "image": img
                })
        return posts
    except: return []

# ============================================================
# আপনার ম্যানুয়াল প্রসেস অনুযায়ী পাবলিশিং
# ============================================================

def publish_processtimeout(5000)
            print("✓ লগইন সফল।")

        # ২. নতুন পোস্ট পেজে যাওয়া
        page.goto(NEW_POST_URL, wait_until="networkidle")
         'Publish' বাটনে ক্লিক
    # স্ক্রিনশট অনুযায়ী এটি নীল বাটন
    page.locator('button(page, post):
    print(f"\n🚀 সিঙ্কিং শুরু: {post['title']}")
    
page.wait_for_timeout(3000)

        # ৩. টাইটেল ইনপুট
        page.:has-text("Publish")').first.click(force=True)
    print("✓ প্রথম পাবলিশ    # ১. নতুন পোস্ট পেজে যাওয়া
    page.goto(NEW_POST_URL, wait_untilfill('input[placeholder*="Enter title"]', post['title'])
        
        # ৪. ডেসক্রিপশন (Rich ক্লিক সম্পন্ন। পপ-আপের জন্য অপেক্ষা...", flush=True)

    # ৬. AI ক্যাটাগরি পপ-="networkidle", timeout=60000)
    page.wait_for_timeout(4000)

     Text Editor) ইনপুট
        editor = page.locator('div[contenteditable="true"]').first
        editor.click()আপ হ্যান্ডলিং (খুবই গুরুত্বপূর্ণ ধাপ)
    try:
        # "Your post belongs to category" লেখা# ২. টাইটেল বসানো (আপনার স্ক্রিনশট অনুযায়ী)
    page.fill('input[placeholder*="
        editor.fill(post['body'])
        print("✓ টাইটেল ও বডি পূর্ণ করা হয়েছে।")

        টি আসা পর্যন্ত অপেক্ষা
        page.wait_for_selector('text="Your post belongs to category"', timeout=20Enter title"]', post['title'])
    print("✓ টাইটেল যুক্ত হয়েছে।")

    # ৩.# ৫. ইমেজ থাম্বনেইল আপলোড (আপনার স্ক্রিনশট অনুযায়ী)
        img_path = download_image(post000)
        print("✓ AI ক্যাটাগরি পপ-আপ দেখা দিয়েছে।", flush=True) কন্টেন্ট বা ডেসক্রিপশন বসানো
    editor = page.locator('div[contenteditable="true"]').first
['image'])
        if img_path:
            # Serey সাধারণত input[type="file"] ব্যবহার
        
        # পপ-আপের ভেতরে থাকা নীল 'Publish' বাটনে ক্লিক
        final_publish =    editor.click()
    editor.fill(post['body'])
    print("✓ কন্টেন্ট যুক্ত হয়েছে।")

    # ৪. ইমেজ বা থাম্বনেইল আপলোড (আপনার স্ক্রিনশট অনুযায়ী)
 করে
            page.set_input_files('input[type="file"]', img_path)
             page.locator('button:has-text("Publish")').last
        final_publish.click(force=    img_path = download_image(post['image'])
    if img_path:
        try:page.wait_for_timeout(5000) # আপলোডের জন্য সময় দিন
            print("✓ ইমেজTrue)
        print("✓ ফাইনাল পাবলিশ বাটনে ক্লিক করা হয়েছে।", flush=True)
    
            page.set_input_files('input[type="file"]', img_path)
            pageexcept Exception as e:
        print(f"! ক্যাটাগরি পপ-আপ পাওয়া যায়নি অথবা এর আপলোড সম্পন্ন।")

        # ৬. প্রথমবার 'Publish' বাটনে ক্লিক
        # আপনার স্ক্রিনশট.wait_for_timeout(5000) # আপলোড হওয়ার সময় দিন
            print("✓ থামর: {str(e)}", flush=True)
        return False

    # ৭. সফলতার মেসেজ এবং অনুযায়ী এটি ডানদিকের নীল বাটন
        page.locator('button:has-text("Publish")').first্বনেইল আপলোড হয়েছে।")
        except:
            print("⚠️ থাম্বনেইল আপলোড করা যায়নি।")

    # ৫. প্রথমবার 'Publish' বাটনে ক্লিক (নীল বাটন)
     রিডাইরেক্ট ভেরিফিকেশন
    try:
        # স্ক্রিনশট অনুযায়ী "Successfully posted.click()
        print("✓ প্রথম পাবলিশ ক্লিক করা হয়েছে। পপ-আপের জন্য অপেক্ষা...")

        # ৭page.locator('button:has-text("Publish")').first.click()
    print("✓ প্রথমবার your article" আসা পর্যন্ত অপেক্ষা
        page.wait_for_selector('text="Successfully posted your article"', timeout=3. AI ক্যাটাগরি পপ-আপ হ্যান্ডলিং (সবচেয়ে গুরুত্বপূর্ণ ধাপ)
        # " Publish ক্লিক করা হয়েছে। AI প্রসেসিং হচ্ছে...")

    # ৬. AI ক্যাটাগরি পপ-0000)
        print("✓ অভিনন্দন! পোস্টটি সফলভাবে পাবলিশ হয়েছে।", flush=True)
Your post belongs to category" মেসেজটির জন্য অপেক্ষা
        page.wait_for_selector('text="Your post belongs to        page.wait_for_timeout(5000)
        print(f"নতুন লিংক: {page.url}", flush category"', timeout=20000)
        
        # পপ-আপের ভেতর যে নীল 'Publish' বাআপ হ্যান্ডলিং (সবচেয়ে গুরুত্বপূর্ণ ধাপ)
    try:
        # পপ-আপ আসা পর্যন্ত অপেক্ষা করুন
        page=True)
        return True
    except:
        print("❌ পাবলিশ কনফার্মেশন পাওয়া যায়নি।", flush=True)
        return False

# ============================================================
# মেইন ফাংশন
# =================================টনটি আছে সেটি ক্লিক করা
        # এটি সাধারণত শেষ বাটন হয় পপ-আপে
        final_publish =.wait_for_selector('text="Your post belongs to category"', timeout=20000)
===========================

def main():
    print("="*50)
    print("STEEM -> SEREY SYNC BOT page.locator('div[role="dialog"] button:has-text("Publish"), button:has-text("        print("✓ AI ক্যাটাগরি পপ-আপ দেখা দিয়েছে।")
        
        # পপ-আপ এর RUNNING")
    print("="*50)

    synced = load_synced()
    stePublish")').last
        final_publish.click()
        print("✓ পপ-আপের পাবলিশ বাট ভেতরের নীল 'Publish' বাটনে ক্লিক করুন
        # আমরা পপ-আপ ডায়ালগের ভেতর থাকাem_posts = get_steem_posts()
    to_sync = [p for p in steem_posts if pনে ক্লিক করা হয়েছে।")

        # ৮. সাকসেস যাচাই করা
        # "Successfully posted your article" বাটনটিকে টার্গেট করছি
        final_btn = page.locator('div[role="dialog"] button['id'] not in synced][:POSTS_PER_RUN]

    if not to_sync:
        print("সিঙ্ক করার মতো নতুন কোনো পোস্ট নেই।", flush=True)
        return

    with sync_ মেসেজটি খুঁজি
        page.wait_for_selector('text="Successfully posted your article"', timeout=3000:has-text("Publish")').last
        if not final_btn.is_visible():
            final_btn = page.locator('button:has-text("Publish")').last
            
        final_btn0)
        print(f"✓ সফলভাবে পোস্ট পাবলিশ হয়েছে! লিঙ্ক: {page.url}")
playwright() as p:
        browser = p.chromium.launch(headless=True) # GitHub এ চলার.click()
        print("✓ দ্বিতীয়বার (Final) Publish ক্লিক করা হয়েছে।")

        # ৭. সফলতা        
        return True

    except Exception as e:
        print(f"❌ এরর: {str জন্য headless=True
        context = browser.new_context(viewport={'width': 1280, 'height যাচাই (আপনার স্ক্রিনশট অনুযায়ী)
        page.wait_for_selector('text="Successfully posted your article"',(e)}")
        # এরর হলে স্ক্রিনশট সেভ করতে পারেন ডিবাগিংয়ের জন্য
        page': 800})
        page = context.new_page()

        # শুরুতে একবার লগইন
        print(" timeout=30000)
        print("✅ পোস্ট সফলভাবে পাবলিশ হয়েছে!")
        return True

.screenshot(path="error_debug.png")
        return False

# ============================================================
# মেইনলগইন করা হচ্ছে...", flush=True)
        page.goto(SEREY, wait_until="domcontentloaded")
        try:
            page.click('text="Log in"', timeout=10000)
    except Exception as e:
        print(f"❌ পাবলিশিং ব্যর্থ হয়েছে: {str(e)}")
        return False

# ============================================================
# মেইন ফাংশন
# ============================================================

def ফাংশন
# ============================================================

def main():
    synced = load_synced()
            page.fill('input[placeholder*="Username"]', SEREY_LOGIN)
            page.fill('input[placeholder*="Private Key"]', SEREY_PASSWORD)
            page.click('button:has-text("Log in")')
            page.wait_for_timeout(5000)
            print main():
    synced = load_synced()
    all_posts = get_steem_posts()
    to_sync = [p for p in all_posts if p['id'] not in synced][:POSTS_    all_posts = get_steem_posts()
    
    to_sync = [p for p in all_posts if p['id'] not in synced][:POSTS_PER_RUN]
    
    if("✓ লগইন সফল।", flush=True)
        except:
            print("❌ লগইন ব্যর্থ হয়েছে।", flush=True not to_sync:
        print("সিঙ্ক করার মতো কোনো নতুন পোস্ট নেই।")
        return

    with syncPER_RUN]

    if not to_sync:
        print("নতুন কোনো পোস্ট নেই।")
        return

    with sync)
            browser.close()
            return

        # পোস্ট পাবলিশ শুরু
        for post in to_sync:_playwright() as p:
        browser = p.chromium.launch(headless=True) # GitHub এ চলার
            if publish_process(page, post):
                synced.add(post['id'])
                save_syn জন্য headless=True
        context = browser.new_context(viewport={'width': 1280, 'heightced(synced)

        browser.close()

    # টেম্প ফাইল ডিলিট
    if os.path.exists(TEMP_IMAGE): os.remove(TEMP_IMAGE)
    print("="*5_playwright() as p:
        # ব্রাউজার লঞ্চ (GitHub Actions এর জন্য হেডলেস)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows': 900})
        page = context.new_page()

        # লগইন ধাপ
        print("0)
    print("কাজ শেষ!")

if __name__ == "__main__":
    main()
