import os
import json
import re
import time
import requests
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
            print(f"RPC: {node}", flush=True)

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
            print(f"RPC failed: {e}", flush=True)

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
# GET STEEM POSTS
# ============================================================

def get_posts():
    print(
        f"Getting posts from @{STEEM_USERNAME}...",
        flush=True
    )

    posts = []
    seen = set()

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

        for p in batch:

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

        last = result[-1]

        new_author = last.get("author")
        new_permlink = last.get("permlink")

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

        time.sleep(0.3)

    posts.reverse()

    print(
        f"Total posts: {len(posts)}",
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

    page.wait_for_timeout(4000)

    # Login trigger
    page.locator(
        'a:has-text("Log in"),'
        'button:has-text("Log in"),'
        'a:has-text("Log In"),'
        'button:has-text("Log In")'
    ).first.click(force=True)

    page.wait_for_timeout(3000)

    page.locator('input[placeholder*="Username"]').first.fill(SEREY_LOGIN)
    page.locator('input[placeholder*="Private Key"]').first.fill(SEREY_PASSWORD)

    page.locator('button:has-text("Log in"), button:has-text("Log In")').last.click(force=True)

    page.wait_for_timeout(7000)

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

    for _ in range(8):

        page.wait_for_timeout(4000)

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
# PUBLISH (FIXED)
# ============================================================

def publish(page, post):

    print("-" * 60)
    print(f"Publishing: {post['title']}", flush=True)

    page.goto(NEW_POST, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # 1. TITLE
    title_box = page.locator('input[placeholder*="Enter title"], input[placeholder*="Title"]').first
    title_box.click()
    title_box.fill(post["title"])
    print("✓ Title filled")
    page.wait_for_timeout(1000)

    # 2. BODY
    editor = page.locator('div[contenteditable="true"]').first
    editor.click()
    editor.fill(post["body"])
    print("✓ Body filled")
    page.wait_for_timeout(2000)

    # 3. THUMBNAIL
    image = download_image(post.get("image"))
    if image:
        try:
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files(image)
            print("✓ Thumbnail set, waiting for upload...")
            page.wait_for_timeout(7000)
        except Exception as e:
            print(f"Thumbnail upload failed: {e}")

    # 4. FIRST PUBLISH BUTTON CLICK
    print("Attempting to click first Publish button...")
    clicked = False
    
    # একাধিক সম্ভাব্য বাটনে ক্লিক চেষ্টা করা
    publish_btn_selectors = [
        'button:has-text("Publish")',
        'div:has-text("Publish")[role="button"]',
        'span:has-text("Publish")'
    ]
    
    for sel in publish_btn_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.scroll_into_view_if_needed()
                btn.click()
                clicked = True
                print(f"✓ Clicked publish with selector: {sel}")
                break
        except:
            pass

    if not clicked:
        # বিকল্প উপায়ে JavaScript দিয়ে ক্লিক
        page.evaluate('''() => {
            const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
            const pub = buttons.find(b => b.innerText && b.innerText.trim() === 'Publish');
            if (pub) pub.click();
        }''')
        print("✓ Executed JS Click on Publish")

    # পপ-আপ আসার জন্য অপেক্ষা
    page.wait_for_timeout(5000)

    # 5. MODAL / AI POP-UP HANDLING
    print("Checking for Final Publish Modal/Pop-up...")
    modal_publish_found = False

    modal_btn_selectors = [
        'div[role="dialog"] button:has-text("Publish")',
        '.modal-content button:has-text("Publish")',
        '.modal button:has-text("Publish")',
        'div.fixed button:has-text("Publish")',
        'div[class*="modal"] button:has-text("Publish")',
        'div[class*="dialog"] button:has-text("Publish")',
        'button:has-text("Confirm")',
        'button:has-text("Submit")'
    ]

    for sel in modal_btn_selectors:
        try:
            m_btn = page.locator(sel).last
            if m_btn.is_visible(timeout=4000):
                print(f"✓ Found Final Modal Button: {sel}")
                page.wait_for_timeout(2000)
                m_btn.click(force=True)
                print("✓ FINAL PUBLISH CLICKED SUCCESSFULLY!")
                modal_publish_found = True
                break
        except:
            continue

    if not modal_publish_found:
        print("⚠️ No pop-up detected, checking if post was submitted directly...")

    # পেজ রিডাইরেক্ট হতে সময় দেওয়া
    page.wait_for_timeout(10000)

    return verify(page, post["title"])

# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("STEEM -> SEREY AUTO SYNC")
    print("=" * 60)

    synced = load_synced()
    print(f"Previously synced: {len(synced)}", flush=True)

    posts = get_posts()
    new_posts = [p for p in posts if p["id"] not in synced]
    print(f"Unsynced posts: {len(new_posts)}", flush=True)

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

    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    main()
