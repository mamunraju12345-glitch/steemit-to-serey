import os
import json
from pathlib import Path
from beem import Steem
from beem.account import Account

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_USERNAME = os.environ["SEREY_USERNAME"]

DATA_FILE = Path("synced_posts.json")


def load_synced_posts():
    if DATA_FILE.exists():
        try:
            return set(json.loads(DATA_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_synced_posts(posts):
    DATA_FILE.write_text(
        json.dumps(sorted(posts), indent=2)
    )


def get_recent_posts():
    steem = Steem(
        nodes=["https://api.steemit.com"]
    )

    account = Account(
        STEEM_USERNAME,
        blockchain_instance=steem
    )

    posts = list(account.get_blog(limit=20))

    result = []

    for post in posts:
        # শুধু নিজের মূল post নেওয়া হবে
        if post["author"] != STEEM_USERNAME:
            continue

        result.append({
            "author": post["author"],
            "permlink": post["permlink"],
            "title": post["title"],
            "body": post["body"],
            "created": str(post["created"]),
            "tags": post.get("json_metadata", {})
        })

    return result


def main():
    print("================================")
    print(" Steemit → Serey Automation")
    print("================================")

    print(f"Steemit: @{STEEM_USERNAME}")
    print(f"Serey:   @{SEREY_USERNAME}")

    synced = load_synced_posts()

    posts = get_recent_posts()

    print(f"Found {len(posts)} recent posts.")

    new_posts = []

    for post in posts:
        post_id = f'{post["author"]}/{post["permlink"]}'

        if post_id in synced:
            continue

        new_posts.append(post)

    print(f"New posts: {len(new_posts)}")

    # Serey publishing অংশ এখানে যুক্ত হবে
    # যখন Serey-এর current publish API/authentication
    # নিশ্চিত করা হবে।

    for post in new_posts:
        print("--------------------------------")
        print("New Steemit post found")
        print("Title:", post["title"])
        print("Permlink:", post["permlink"])

    print("--------------------------------")
    print("Automation scan completed.")


if __name__ == "__main__":
    main()
