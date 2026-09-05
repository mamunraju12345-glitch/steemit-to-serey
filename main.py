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
            r = requests.post(
                node,
                json=payload,
                timeout=20
            )

            r.raise_for_status()
            data = r.json()

            if "error" in data:
                raise Exception(data["error"])

            return data["result"]

        except Exception as e:
            continue

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
    with open(
        SYNC_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            sorted(data),
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# CLEAN BODY + IMAGE
# ============================================================

def clean_post(body, metadata):
    image = None

    try:
        meta = json.loads(metadata or "{}")

        for x in meta.get("image", []):
            if isinstance(x, str):
                image = x
                break

    except Exception:
        pass

    if not image:
        m = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)',
            body,
            re.I
        )
        if m:
            image = m.group(1)

    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    body = re.sub(
        r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?',
        '',
        body,
        flags=re.I
    )

    body = re.sub(
        r'\n{3,}',
        '\n\n',
        body
    )

    return body.strip(), image


# ============================================================
# GET STEEM POSTS (গত ১ বছর)
# ============================================================

def get_posts():
    print(
        f"Getting posts from last 1 year for @{STEEM_USERNAME}...",
        flush=True
    )

    posts = []
    seen = set()
    
    # ১ বছর আগের সময় নির্ধারণ
    one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)

    start_author = None
    start_permlink = None

    while len(posts) < 5000:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        batch = result[1:] if start_author else result

        if not batch:
            break

        old_post_found = False
        for p in batch:
            
            # তারিখ চেক
            created_dt = datetime.strptime(p['created'], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            
            if created_dt < one_year_ago:
                old_post_found = True
                continue

            if p.get("author") != STEEM_USERNAME:
                continue

            author = p.get("author", "")
            permlink = p.get("permlink", "")

            if not permlink:
                continue

            pid = f"{author}/{permlink}"

            if pid in seen:
                continue

            seen.add(pid)

            body, image = clean_post(
                p.get("body", ""),
                p.get("json_metadata", "{}")
            )

            posts.append({
                "id": pid,
                "title": p.get("title", "").strip(),
                "body": body,
                "image": image,
                "category": p.get("category", "")
            })

        if old_post_found:
            break

        last = result[-1]
        start_author, start_permlink = last.get("author"), last.get("permlink")

        if len(result) < 100:
            break

        time.sleep(0.3)

    # পুরনো পোস্ট আগে (Oldest first)
    posts.reverse()

    print(
        f"Total eligible posts: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if not url:
        return None

    try:
        print(
            f"Downloading image: {url}",
            flush=True
        )

        r = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        r.raise_for_status()

        if "image" not in r.headers.get(
            "content-type", ""
        ).lower():
            return None

        with open(TEMP_IMAGE, "wb") as f:
            f.write(r.content)

        return TEMP_IMAGE

    except Exception as e:
        print(
            f"Image download failed: {e}",
            flush=True
        )
        return None


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print("Logging into Serey...", flush=True)

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    # পেজ লোড হওয়ার জন্য অতিরিক্ত বিরতি
    page.wait_for_timeout(5000)

    # লগইন বাটন খোঁজা
    login_btn = page.locator('a:has-text("Log in"), button:has-text("Log in"), a:has-text("Log In"), button:has-text("Log In")').first
    login_btn.wait_for(state="visible", timeout=30000)
    login_btn.click(force=True)

    page.wait_for_timeout(3000)

    page.locator('input[placeholder*="Username"]').first.fill(SEREY_LOGIN)
    page.locator('input[placeholder*="Private Key"]').first.fill(SEREY_PASSWORD)

    page.locator('button:has-text("Log in"), button:has-text("Log In")').last.click(force=True)

    page.wait_for_timeout(8000)

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )


# ============================================================
# VERIFY
# ============================================================

def verify(page, title):

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    for _ in range(5):

        page.wait_for_timeout(6000)

        url = page.url
        print(f"Current URL: {url}", flush=True)

        if "/authors/" in url and "/blog/post/new" not in url:
            print("✓ SUCCESS: POST PUBLISHED AND REDIRECTED!", flush=True)
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
# PUBLISH
# ============================================================

def publish(page, post):

    print("-" * 60)
    print(f"Publishing: {post['title']}", flush=True)

    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # TITLE
    page.locator('input[placeholder*="Enter title"]').fill(post["title"])

    # BODY
    editor = page.locator('div[contenteditable="true"]').first
    editor.click()
    editor.fill(post["body"])

    # THUMBNAIL (১০ সেকেন্ড বিরতিসহ)
    image = download_image(post.get("image"))
    if image:
        try:
            page.set_input_files('input[type="file"]', image)
            print("⌛ Waiting for thumbnail upload...", flush=True)
            page.wait_for_timeout(10000) 
            print("✓ Thumbnail uploaded")
        except Exception as e:
            print(f"Thumbnail failed: {e}")

    # FIRST PUBLISH CLICK
    page.get_by_text("Publish", exact=True).last.click(force=True)
    print("✓ FIRST PUBLISH CLICKED. Waiting for AI Pop-up...")

    # AI ক্যাটাগরি পপ-আপ হ্যান্ডলিং
    try:
        final_btn = page.locator('div[role="dialog"] button:has-text("Publish"), .modal-content button:has-text("Publish")').last
        final_btn.wait_for(state="visible", timeout=60000)
        final_btn.click(force=True)
        print("✓ AI Pop-up detected. Clicking FINAL Publish...")
        page.wait_for_timeout(15000)

    except Exception as e:
        print(f"❌ Final Publish failed or Pop-up didn't appear: {e}")
        return False

    return verify(page, post["title"])


# ============================================================
# MAIN
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
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
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
            if os.path.exists(TEMP_IMAGE):
                try: os.remove(TEMP_IMAGE)
                except: pass
            browser.close()

if __name__ == "__main__":
    main()
