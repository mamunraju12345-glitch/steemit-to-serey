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


def main():
    print("=" * 60)
    print("       STEEMIT → SEREY AUTOMATION (DEBUG MODE)")
    print("=" * 60)

    posts = get_recent_posts()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print("\nOpening Serey.io to inspect login elements...")
        try:
            page.goto("https://serey.io", timeout=60000)
            page.wait_for_timeout(4000)

            # Click Log In button in Navbar
            login_nav_btn = page.locator('.nav-btn-space, button:has-text("Log in"), a:has-text("Log in")').first
            login_nav_btn.click()
            page.wait_for_timeout(4000)

            # Print Modal Inputs details to GitHub log
            inputs = page.locator('input').all()
            print(f"\n--- Found {len(inputs)} input fields on Serey ---")
            for idx, inp in enumerate(inputs):
                placeholder = inp.get_attribute("placeholder") or ""
                name = inp.get_attribute("name") or ""
                inp_type = inp.get_attribute("type") or ""
                inp_id = inp.get_attribute("id") or ""
                print(f"Input #{idx+1} -> type='{inp_type}', placeholder='{placeholder}', name='{name}', id='{inp_id}'")

        except Exception as e:
            print(f"❌ Error during debug inspection: {e}")

        browser.close()

    print("\n" + "=" * 60)
    print("DEBUG INSPECTION COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
