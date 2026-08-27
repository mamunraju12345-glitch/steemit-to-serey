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
    first_image_url = None

    try:
        meta = json.loads(json_metadata_str)
        if isinstance(meta, dict) and "image" in meta and isinstance(meta["image"], list) and meta["image"]:
            first_image_url = meta["image"][0]
    except Exception:
        pass

    if not first_image_url:
        img_match = re.search(r'https?://\S+\.(?:png|jpg|jpeg|gif|webp)', body_text, re.IGNORECASE)
        if img_match:
            first_image_url = img_match.group(0)

    clean_body = re.sub(r'!\[.*?\]\(.*?\)', '', body_text)
    clean_body = re.sub(r'https?://\S+\.(?:png|jpg|jpeg|gif|webp)', '', clean_body, flags=re.IGNORECASE)
    clean_body = re.sub(r'\n\s*\n', '\n\n', clean_body).strip()

    return first_image_url, clean_body


def get_recent_posts():
    print(f"\nFetching ALL historical posts from Steemit: @{STEEM_USERNAME}", flush=True)
    all_posts = []
    seen_permlinks = set()
    start_author = None
    start_permlink = None

    while True:
        params = {"tag": STEEM_USERNAME, "limit": 100}
        if start_author and start_permlink:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        result = steem_rpc("condenser_api.get_discussions_by_blog", params)
        if not result:
            break

        batch = result[1:] if (start_author and start_permlink) else result
        if not batch:
            break

        for post in batch:
            if post.get("author") != STEEM_USERNAME:
                continue

            permlink = post.get("permlink")
            if permlink in seen_permlinks:
                continue
            seen_permlinks.add(permlink)

            raw_body = post.get("body", "")
            meta_str = post.get("json_metadata", "{}")
            image_url, clean_body = extract_image_and_clean_body(raw_body, meta_str)

            all_posts.append({
                "author": post.get("author"),
                "permlink": permlink,
                "title": post.get("title", ""),
                "body": clean_body,
                "image": image_url,
                "category": post.get("category", ""),
                "created": post.get("created", "")
            })

        last_post = result[-1]
        new_start_author = last_post.get("author")
        new_start_permlink = last_post.get("permlink")

        if new_start_author == start_author and new_start_permlink == start_permlink:
            break

        start_author = new_start_author
        start_permlink = new_start_permlink

        if len(result) < 100 or len(all_posts) >= 1000:
            break

        time.sleep(0.3)

    all_posts.reverse()
    return all_posts


def publish_to_serey(page, post):
    print(f"\n---> Publishing to Serey: {post['title']}", flush=True)
    temp_img_path = "temp_thumbnail.jpg"

    try:
        # 1. Open New Post URL
        page.goto("https://serey.io/blog/post/new", timeout=60000)
        page.wait_for_timeout(4000)

        # 2. Fill Title
        title_box = page.locator('input[placeholder*="title" i], input[placeholder*="Title"]').first
        title_box.fill(post["title"])
        print("  - Title filled!", flush=True)

        # 3. Fill Content (Clean Body)
        body_box = page.locator('div[contenteditable="true"], textarea[placeholder*="content" i], textarea').first
        body_box.fill(post["body"])
        print("  - Clean body content filled!", flush=True)
        page.wait_for_timeout(2000)

        # 4. Upload Thumbnail Image
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
                        page.wait_for_timeout(4000)
            except Exception as img_err:
                print(f"  - Thumbnail upload skipped: {img_err}", flush=True)

        # 5. Click First "Publish" Button
        page.locator('button:has-text("Publish")').first.click(force=True)
        print("  - First Publish button clicked!", flush=True)
        page.wait_for_timeout(6000)

        # 6. Click Category Selector inside modal
        try:
            dropdown = page.locator('div:has-text("Select category"), .ant-modal-content .ant-select, input[placeholder*="category" i]').first
            dropdown.click(force=True)
            page.wait_for_timeout(1500)

            option = page.locator('.ant-select-item-option, div[title="Tech"], div[title="Crypto"], li').first
            if option.count() > 0:
                option.click(force=True)
            else:
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
            print("  - Category selected!", flush=True)
        except Exception as err:
            print(f"  - Category auto-selecting via keyboard...", flush=True)
            page.keyboard.press("Tab")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")

        page.wait_for_timeout(2000)

        # 7. Click Final "Publish" Button inside Category Modal
        final_publish = page.locator('.ant-modal-content button.ant-btn-primary, .ant-modal-content button:has-text("Publish"), .ant-modal-footer button:has-text("Publish")').last
        final_publish.click(force=True)
        print("  - Final Publish button clicked. Verifying on profile...", flush=True)
        page.wait_for_timeout(12000)

        # 8. Profile Verification Check
        profile_url = f"https://serey.io/authors/@{SEREY_LOGIN}"
        page.goto(profile_url, timeout=30000)
        page.wait_for_timeout(4000)

        # Verify if title exists on profile page
        short_title = post["title"][:25].strip()
        if short_title in page.content():
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)
            print(f"✅ VERIFIED & PUBLISHED ON SEREY: {post['title']}", flush=True)
            return True
        else:
            page.screenshot(path="verification_failed.png")
            print(f"❌ Post could not be verified on Serey profile page ({profile_url}).", flush=True)
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)
            return False

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

    print(f"Total historical posts fetched: {len(posts)}", flush=True)
    print(f"Unsynced posts available: {len(new_posts)}", flush=True)

    # LIMIT TO 1 POST PER RUN
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
    print("SYNC COMPLETED SUCCESSFULLY", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
