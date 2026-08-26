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
    print(f"\nFetching posts from Steemit: @{STEEM_USERNAME}")
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
    """Playwright using browser to log in and post on Serey"""
    print(f"\nPublishing to Serey: {post['title']}")
    
    # 1. Open Serey Submit/Create page
    page.goto("https://serey.io/create-post", timeout=60000)
    page.wait_for_timeout(3000)

    # 2. Fill Title, Category, and Body
    try:
        page.fill('input[placeholder*="Title"], input[name="title"]', post["title"])
        category = post["category"] if post["category"] else "general"
        page.fill('input[placeholder*="Tag"], input[name="tags"]', category)
        page.fill('textarea[placeholder*="Story"], textarea[name="body"], div[contenteditable="true"]', post["body"])
        
        # 3. Click Submit/Publish
        page.click('button:has-text("Publish"), button:has-text("Post")')
        page.wait_for_timeout(5000)
        print(f"✅ Successfully published on Serey: {post['title']}")
        return True
    except Exception as e:
        print(f"❌ Failed to publish post on Serey: {e}")
        return False


def main():
    print("=" * 60)
    print("       STEEMIT → SEREY AUTOMATION")
    print("=" * 60)

    synced_posts = load_synced_posts()
    posts = get_recent_posts()

    new_posts = []
    for post in posts:
        post_id = f'{post["author"]}/{post["permlink"]}'
        if post_id not in synced_posts:
            new_posts.append(post)

    print(f"Total posts found: {len(posts)}")
    print(f"New posts to publish: {len(new_posts)}")

    if not new_posts:
        print("No new posts to sync!")
        return

    # Start Playwright Browser
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Login to Serey
        print("\nLogging into Serey.io...")
        page.goto("https://serey.io/login", timeout=60000)
        page.wait_for_timeout(3000)

        try:
            page.fill('input[name="username"], input[type="text"]', SEREY_LOGIN)
            page.fill('input[name="password"], input[type="password"]', SEREY_PASSWORD)
            page.click('button[type="submit"], button:has-text("Log in")')
            page.wait_for_timeout(5000)
            print("✅ Logged into Serey successfully!")
        except Exception as e:
            print(f"❌ Login failed: {e}")
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

    print("\n" + "=" * 60)
    print("SYNC COMPLETED SUCCESSFULLY")
    print("=" * 60)


if __name__ == "__main__":
    main()
