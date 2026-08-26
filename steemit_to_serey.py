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
    print(f"\n---> Inspecting Serey UI for: {post['title']}", flush=True)
    try:
        page.goto("https://serey.io", timeout=60000)
        page.wait_for_timeout(4000)

        # Inspect all interactive links and buttons when logged in
        all_elements = page.locator('a, button').all()
        print(f"\n--- Found {len(all_elements)} buttons/links on Serey after login ---", flush=True)
        for idx, el in enumerate(all_elements):
            try:
                href = el.get_attribute("href") or ""
                txt = el.inner_text().strip()
                cls = el.get_attribute("class") or ""
                if txt or href:
                    print(f"Element #{idx+1} -> text='{txt}', href='{href}', class='{cls}'", flush=True)
            except Exception:
                pass

        return False
    except Exception as e:
        print(f"❌ Error during inspection: {e}", flush=True)
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

        # Inspect UI for first new post
        if new_posts:
            publish_to_serey(page, new_posts[0])

        browser.close()

    print("\n" + "=" * 60, flush=True)
    print("INSPECTION COMPLETED", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
