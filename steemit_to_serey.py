import os
import json
import requests
import time

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_USERNAME = os.environ.get("SEREY_USERNAME", "mamun")

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
    """Try each Steem RPC node until one works."""

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }

    last_error = None

    for node in STEEM_NODES:

        try:
            print(f"Connecting to: {node}")

            response = requests.post(
                node,
                json=payload,
                headers={
                    "Content-Type": "application/json"
                },
                timeout=20
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise RuntimeError(str(data["error"]))

            print(f"✅ Connected: {node}")

            return data["result"]

        except Exception as e:

            last_error = e

            print(f"❌ Failed: {node}")
            print(f"   {e}")

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed. Last error: {last_error}"
    )


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

        json.dump(
            sorted(posts),
            file,
            indent=2,
            ensure_ascii=False
        )


def get_recent_posts():

    print()
    print("=" * 60)
    print(f"Fetching posts from @{STEEM_USERNAME}")
    print("=" * 60)

    result = steem_rpc(
        "condenser_api.get_discussions_by_blog",
        {
            "tag": STEEM_USERNAME,
            "limit": 20
        }
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
            "created": post.get("created", ""),
            "json_metadata": post.get("json_metadata", "{}")
        })

    return posts


def main():

    print()
    print("=" * 60)
    print("       STEEMIT → SEREY AUTOMATION")
    print("=" * 60)

    print(f"Steemit account : @{STEEM_USERNAME}")
    print(f"Serey account   : @{SEREY_USERNAME}")

    synced_posts = load_synced_posts()

    posts = get_recent_posts()

    print()
    print(f"Total posts found: {len(posts)}")

    new_posts = []

    for post in posts:

        post_id = (
            f'{post["author"]}/{post["permlink"]}'
        )

        if post_id in synced_posts:
            continue

        new_posts.append(post)

    print(f"New posts found: {len(new_posts)}")

    for post in new_posts:

        print()
        print("-" * 60)
        print("NEW POST")
        print("-" * 60)

        print("Title    :", post["title"])
        print("Author   :", post["author"])
        print("Permlink :", post["permlink"])
        print("Created  :", post["created"])
        print("Category :", post["category"])

        print()
        print("Steemit URL:")
        print(
            f'https://steemit.com/{post["category"]}/'
            f'@{post["author"]}/{post["permlink"]}'
        )

        # --------------------------------------------------
        # SEREY PUBLISHING
        # --------------------------------------------------
        #
        # এখানে Serey publishing function যুক্ত হবে।
        #
        # Serey publish সফল হওয়ার আগে post-কে
        # synced হিসেবে mark করা হবে না।
        #
        # --------------------------------------------------

    print()
    print("=" * 60)
    print("SCAN COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
