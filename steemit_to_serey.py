import os
import json
from beem import Steem
from beem.account import Account

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_USERNAME = os.environ.get("SEREY_USERNAME", "mamun")

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.steem.house",
    "https://steemd.privex.io",
]

DATA_FILE = "synced_posts.json"


def load_synced():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_synced(posts):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(posts), f, indent=2)


def get_steem():
    """
    Force beem to use Steem nodes.
    Do not use Hive nodes.
    """
    last_error = None

    for node in STEEM_NODES:
        try:
            print(f"Connecting to Steem node: {node}")

            steem = Steem(
                node=node,
                keys=[]
            )

            # Force a simple Steem RPC call
            steem.get_block(1)

            print(f"✅ Connected: {node}")
            return steem

        except Exception as e:
            last_error = e
            print(f"⚠️ Node failed: {node}")
            print(f"   {e}")

    raise RuntimeError(
        f"Could not connect to any Steem node. Last error: {last_error}"
    )


def get_recent_posts(steem):
    print(f"Reading posts from @{STEEM_USERNAME}...")

    account = Account(
        STEEM_USERNAME,
        blockchain_instance=steem
    )

    posts = account.get_blog(
        limit=20,
        raw_data=False
    )

    result = []

    for post in posts:

        author = post.get("author")

        if author != STEEM_USERNAME:
            continue

        permlink = post.get("permlink")

        if not permlink:
            continue

        result.append({
            "author": author,
            "permlink": permlink,
            "title": post.get("title", ""),
            "body": post.get("body", ""),
            "created": str(post.get("created", "")),
            "category": post.get("category", ""),
        })

    return result


def main():

    print("=" * 50)
    print(" STEEMIT → SEREY AUTOMATION")
    print("=" * 50)

    print(f"Steemit account : @{STEEM_USERNAME}")
    print(f"Serey account   : @{SEREY_USERNAME}")

    synced = load_synced()

    steem = get_steem()

    posts = get_recent_posts(steem)

    print(f"\nFound {len(posts)} posts.")

    new_posts = []

    for post in posts:

        post_id = f'{post["author"]}/{post["permlink"]}'

        if post_id in synced:
            continue

        new_posts.append(post)

    print(f"New posts found: {len(new_posts)}")

    for post in new_posts:

        print("\n" + "-" * 50)
        print("NEW STEEMIT POST")
        print("-" * 50)

        print("Title:", post["title"])
        print("Author:", post["author"])
        print("Permlink:", post["permlink"])
        print("Created:", post["created"])

        # Serey publishing will be handled here.
        # We intentionally do not mark the post as synced
        # until Serey publishing succeeds.

    print("\n" + "=" * 50)
    print("SCAN COMPLETED")
    print("=" * 50)


if __name__ == "__main__":
    main()
