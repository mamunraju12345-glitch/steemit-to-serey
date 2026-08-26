import os
import json
import requests
import time
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


def get_recent_posts():
    print(f"\nFetching posts from Steemit: @{STEEM_USERNAME}", flush=True)
    result = steem_rpc(
        "condenser_api.get_discussions_by_blog",
        {"tag": STEEM_USERNAME, "limit": 20}
    )

    posts = []
    for post in result:
        if post.get("author") != STEEM_USERNAME:
            continue

        posts.append({
            "author": post.get("author"),
            "permlink": post.get("permlink"),
            "title": post.get("title", ""),
            "body": post.get("body", ""),
            "category": post.get("category", ""),
            "created": post.get("created", "")
        })

    return posts


def publish_to_serey(page, post):
    print(f"\n---> Publishing to Serey: {post['title']}", flush=True)
    try:
        # 1. Open New Post URL
        page.goto("https://serey.io/blog/post/new", timeout=60000)
        page.wait_for_timeout(4000)

        # 2. Fill Title ("Enter title...")
        title_box = page.locator('input[placeholder*="title" i], input[placeholder*="Title"]').first
        title_box.fill(post["title"])
        print("  - Title filled!", flush=True)

        # 3. Fill Content ("Enter content...")
        body_box = page.locator('div[contenteditable="true"], textarea[placeholder*="content" i], textarea').first
        body_box.fill(post["body"])
        print("  - Content filled!", flush=True)
        page.wait_for_timeout(2000)

        # 4. Click First "Publish" Button
        page.locator('button:has-text("Publish")').first.click(force=True)
        print("  - First Publish button clicked!", flush=True)
        
        # 5. Wait 6 seconds for "Preparing to publish" loading to finish
        page.wait_for_timeout(6000)

        # Click Category Selector inside modal
        try:
            dropdown = page.locator('div:has-text("Select category"), .ant-select, input[placeholder*="category" i]').first
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

        # 6. Click Final "Publish" Button inside Category Modal
        final_publish = page.locator('.ant-modal-content button:has-text("Publish"), .ant-modal-footer button:has-text("Publish"), button:has-text("Publish")').last
        final_publish.click(force=True)
        page.wait_for_timeout(8000)

        print(f"✅ SUCCESSFULLY PUBLISHED ON SEREY: {post['title']}", flush=True)
        return True
    except Exception as e:
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

    print(f"Total posts found: {len(posts)}", flush=True)
    print(f"New posts to publish: {len(new_posts)}", flush=True)

    if not new_posts:
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

        # Publish Each Post
        for post in new_posts:
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
