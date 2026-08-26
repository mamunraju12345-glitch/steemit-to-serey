import os
import json
import requests
import time
import re
from playwright.sync_api import sync_playwright

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_LOGIN = os.environ.get("SEREY_LOGIN", os.environ.get("SEREY_USERNAME", ""))
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "")

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
    "https://api.steem-fanbase.com",
    "https://api.steem.buzz",
    "https://steemd.privex.io",
    "https://api.steemitdev.com",
]

DATA_FILE = "synced_posts.json"


def steem_rpc(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    last_error = None

    for node in STEEM_NODES:
        try:
            response = requests.post(
                node,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(str(data["error"]))

            return data["result"]
        except Exception as e:
            last_error = e
            time.sleep(1)

    raise RuntimeError(f"All Steem RPC nodes failed. Last error: {last_error}")


def load_synced_posts():
    if not os.path.exists(DATA_FILE):
        return set()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return set(data)
    except Exception:
        return set()


def save_synced_posts(posts):
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(posts), file, indent=2, ensure_ascii=False)


def extract_image_and_clean_body(body_text, json_metadata_str):
    """Extract main image for thumbnail & clean raw image links from body"""
    first_image_url = None

    # 1. Try to get main image from json_metadata
    try:
        meta = json.loads(json_metadata_str)
        if isinstance(meta, dict) and "image" in meta and isinstance(meta["image"], list) and meta["image"]:
            first_image_url = meta["image"][0]
    except Exception:
        pass

    # 2. Fallback: regex search first image in body
    if not first_image_url:
        img_match = re.search(r'https?://\S+\.(?:png|jpg|jpeg|gif|webp)', body_text, re.IGNORECASE)
        if img_match:
            first_image_url = img_match.group(0)

    # 3. Clean body text (remove markdown images and raw image links)
    clean_body = re.sub(r'!\[.*?\]\(.*?\)', '', body_text)
    clean_body = re.sub(r'https?://\S+\.(?:png|jpg|jpeg|gif|webp)', '', clean_body, flags=re.IGNORECASE)
    clean_body = re.sub(r'\n\s*\n', '\n\n', clean_body).strip()

    return first_image_url, clean_body


def get_recent_posts():
    print(f"\nFetching posts from Steemit: @{STEEM_USERNAME}", flush=True)
    result = steem_rpc(
        "condenser_api.get_discussions_by_blog",
        {"tag": STEEM_USERNAME, "limit": 50}
    )

    posts = []
    for post in result:
        if post.get("author") != STEEM_USERNAME:
            continue

        raw_body = post.get("body", "")
        meta_str = post.get("json_metadata", "{}")
        image_url, clean_body = extract_image_and_clean_body(raw_body, meta_str)

        posts.append({
            "author": post.get("author"),
            "permlink": post.get("permlink"),
            "title": post.get("title", ""),
            "body": clean_body,
            "image": image_url,
            "category": post.get("category", ""),
            "created": post.get("created", "")
        })

    # Reverse list to process OLDEST posts first (1 year ago to recent)
    posts.reverse()
    return posts


def publish_to_serey(page, post):
    print(f"\n---> Publishing to Serey: {post['title']}", flush=True)
    temp_img_path = "temp_thumbnail.jpg"
    
    try:
        # 1. Open New Post URL
        page.goto("https://serey.io/blog/post/new", timeout=60000)
        page.wait_for_timeout(4000)

        # 2. Fill Title ("Enter title...")
        title_box = page.locator('input[placeholder*="title" i], input[placeholder*="Title"]').first
        title_box.fill(post["title"])
        print("  - Title filled!", flush=True)

        # 3. Fill Clean Body Content ("Enter content...")
        body_box = page.locator('div[contenteditable="true"], textarea[placeholder*="content" i], textarea').first
        body_box.fill(post["body"])
        print("  - Clean body content filled!", flush=True)

        # 4. Upload Thumbnail Image (If image URL exists)
        if post.get("image"):
            try:
                print(f"  - Downloading thumbnail image...", flush=True)
                img_resp = requests.get(post["image"], timeout=15)
                if img_resp.status_code == 200:
                    with open(temp_img_path, "wb") as f:
                        f.write(img_resp.content)

                    file_input = page.locator('input[type="file"]').first
                    if file_input.count() > 0:
                        file_input.set_input_files(temp_img_path)
                        print("  - Thumbnail image uploaded!", flush=True)
                        page.wait_for_timeout(3000)
            except Exception as img_err:
                print(f"  - Thumbnail upload skipped: {img_err}", flush=True)

        page.wait_for_timeout(2000)

        # 5. Click First "Publish" Button
        page.locator('button:has-text("Publish")').first.click(force=True)
        print("  - First Publish button clicked!", flush=True)
        page.wait_for_timeout(6000)

        # 6. Handle Category Modal Popup ("Please choose category")
        page.wait_for_selector('.ant-modal-content', timeout=10000)
        modal = page.locator('.ant-modal-content')

        # Click Category Selector inside modal
        cat_select = modal.locator('.ant-select-selector, .ant-select').first
        cat_select.click(force=True)
        page.wait_for_timeout(1500)

        # Select first option in dropdown
        option = page.locator('.ant-select-item-option, .ant-select-dropdown div').first
        if option.count() > 0:
            option.click(force=True)
        else:
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
        print("  - Category selected!", flush=True)
        page.wait_for_timeout(1500)

        # 7. Click Final "Publish" Button inside Category Modal
        modal.locator('button:has-text("Publish")').first.click(force=True)
        page.wait_for_timeout(8000)

        # Clean up temp image file
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)

        print(f"✅ SUCCESSFULLY PUBLISHED ON SEREY: {post['title']}", flush=True)
        return True
    except Exception as e:
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)
        print(f"❌ Failed to publish post on Serey: {e}", flush=True)
        return False


def main():
    print("=" * 60, flush=True)
    print("       STEEMIT → SEREY AUTOMATION", flush=True)
    print("=" * 60, flush=True)

    synced_posts = load_synced_posts()
    posts = get_recent_posts()

    new_posts = []
    for post in posts:
        post_id = f'{post["author"]}/{post["permlink"]}'
        if post_id not in synced_posts:
            new_posts.append(post)

    print(f"Total posts fetched: {len(posts)}", flush=True)
    print(f"Unsynced posts available: {len(new_posts)}", flush=True)

    # LIMIT TO EXACTLY 1 POST PER RUN
    new_posts_to_run = new_posts[:1]
    print(f"Publishing in this run (Limit = 1): {len(new_posts_to_run)}", flush=True)

    if not new_posts_to_run:
        print("No new posts to sync!", flush=True)
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print("\nLogging into Serey.io...", flush=True)
        try:
            page.goto("https://serey.io", timeout=60000)
            page.wait_for_timeout(4000)

            print("Clicking Log in button...", flush=True)
            page.locator('a:has-text("Log in"), button:has-text("Log in"), a:has-text("Log In"), button:has-text("Log In")').first.click(force=True)
            page.wait_for_timeout(5000)

            page.wait_for_selector('input[placeholder="Username"], input[placeholder*="Username"]', timeout=20000)

            page.locator('input[placeholder="Username"], input[placeholder*="Username"]').first.fill(SEREY_LOGIN)
            page.locator('input[placeholder="Private Key or Password"], input[placeholder*="Private Key"]').first.fill(SEREY_PASSWORD)

            page.locator('.ant-modal-content button:has-text("Log in"), .ant-modal-content button:has-text("Log In"), button:has-text("Log in")').last.click(force=True)
            page.wait_for_timeout(6000)
            print("✅ LOGGED INTO SEREY SUCCESSFULLY!", flush=True)
        except Exception as e:
            print(f"❌ Login failed: {e}", flush=True)
            browser.close()
            return

        # Publish 1 Post per run
        for post in new_posts_to_run:
            success = publish_to_serey(page, post)
            if success:
                post_id = f'{post["author"]}/{post["permlink"]}'
                synced_posts.add(post_id)
                save_synced_posts(synced_posts)

        browser.close()

    print("\n" + "=" * 60, flush=True)
    print("SYNC COMPLETED SUCCESSFULLY")
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
