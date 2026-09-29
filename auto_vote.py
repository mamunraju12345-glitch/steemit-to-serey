import json
import os
import time
import requests

# ============================================================
# SETTINGS & TOKEN FOR MAMUN
# ============================================================

SEREY_LOGIN = os.environ.get("SEREY_LOGIN", "mamun").replace("@", "").strip()

FALLBACK_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoicG9zdGluZyIsInVzZXJuYW1lIjoibWFtdW4iLCJwYXNzd29yZCI6IjVLNDhVSEF1a3JuTkNHUGVxeTczUkRNTlRBbm1HRm1RY2I4MzRrZUxNSndCQnpkWWJLQyIsImlhdCI6MTc5MDQyOTg0OH0.v5tdje9uHEQ6ckavhtAgQxQHEaPIqji1H09Jvk2uiTk"
SEREY_TOKEN = os.environ.get("SEREY_TOKEN", FALLBACK_TOKEN).strip()

AUTH_HEADER = (
    f"Bearer {SEREY_TOKEN}"
    if not SEREY_TOKEN.startswith("Bearer ")
    else SEREY_TOKEN
)

VOTE_API = "https://bengali.serey.io/api/votes/up"
VOTED_FILE = "voted_posts.json"
MAX_VOTES_PER_RUN = 10
VOTE_WEIGHT = 100

# ============================================================
# LOAD / SAVE VOTED POSTS
# ============================================================


def init_file():
    if not os.path.exists(VOTED_FILE):
        with open(VOTED_FILE, "w", encoding="utf-8") as f:
            f.write("[]")


def load_voted():
    init_file()
    try:
        with open(VOTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def save_voted(data):
    with open(VOTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(data), f, ensure_ascii=False, indent=2)


# ============================================================
# FETCH POSTS (LIVE ENDPOINTS ONLY)
# ============================================================


def parse_post_data(raw_data):
    """রেসপন্স অবজেক্ট থেকে পোস্ট লিস্ট ফিল্টার করা"""
    if isinstance(raw_data, list):
        return raw_data
    if isinstance(raw_data, dict):
        for key in ["posts", "data", "result", "rows"]:
            if (
                key in raw_data
                and isinstance(raw_data[key], list)
                and len(raw_data[key]) > 0
            ):
                return raw_data[key]
            if (
                key in raw_data
                and isinstance(raw_data[key], dict)
                and "posts" in raw_data[key]
            ):
                return raw_data[key]["posts"]
    return []


def get_posts_to_vote():
    print("Fetching recent posts from Bengali Community...", flush=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Authorization": AUTH_HEADER,
        "Origin": "https://bengali.serey.io",
        "Referer": "https://bengali.serey.io/",
    }

    # টেস্ট ১: bengali.serey.io এর নিজস্ব ইন্টারনাল এপিআই (POST মেথড - 405 ফিক্স)
    try:
        url = "https://bengali.serey.io/api/posts"
        payload = {"limit": 20, "community_id": 2, "offset": 0}
        print(f"Trying POST: {url}...", flush=True)
        r = requests.post(url, json=payload, headers=headers, timeout=12)
        print(f"Response: {r.status_code}", flush=True)
        if r.status_code == 200:
            posts = parse_post_data(r.json())
            if posts:
                print(
                    f"✓ Found {len(posts)} posts via Bengali Serey API!",
                    flush=True,
                )
                return posts
    except Exception as e:
        print(f"Error bengali.serey.io POST: {e}", flush=True)

    # টেস্ট ২: https://api.serey.io লাইভ নোডে সেরি RPC কল
    try:
        url = "https://api.serey.io"
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": [
                "condenser_api",
                "get_discussions_by_created",
                [{"tag": "serey-bengali", "limit": 20}],
            ],
            "id": 1,
        }
        print(f"Trying Node RPC: {url}...", flush=True)
        r = requests.post(url, json=payload, timeout=12)
        print(f"Response: {r.status_code}", flush=True)
        if r.status_code == 200:
            posts = r.json().get("result", [])
            if posts:
                print(f"✓ Found {len(posts)} posts via Live RPC!", flush=True)
                return posts
    except Exception as e:
        print(f"Error api.serey.io RPC: {e}", flush=True)

    # টেস্ট ৩: Frontend Community Feed API (Web App যেখান থেকে পোস্ট লোড করে)
    web_feed_urls = [
        "https://bengali.serey.io/api/feeds/community/2",
        "https://bengali.serey.io/api/posts/community/2?limit=20",
        "https://bengali.serey.io/api/posts/created?limit=20",
    ]

    for u in web_feed_urls:
        try:
            print(f"Checking URL: {u}...", flush=True)
            r = requests.get(u, headers=headers, timeout=10)
            print(f"Status: {r.status_code}", flush=True)
            if r.status_code == 200:
                posts = parse_post_data(r.json())
                if posts:
                    print(f"✓ Found {len(posts)} posts from {u}!", flush=True)
                    return posts
        except Exception as e:
            print(f"Error fetching from {u}: {e}", flush=True)

    return []


# ============================================================
# CAST VOTE
# ============================================================


def cast_vote(author, permlink):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "authorization": AUTH_HEADER,
        "Origin": "https://bengali.serey.io",
        "Referer": "https://bengali.serey.io/blog",
    }

    payload = {
        "author": author,
        "permlink": permlink,
        "weight": VOTE_WEIGHT,
        "vote_type": "post",
    }

    try:
        r = requests.post(VOTE_API, json=payload, headers=headers, timeout=20)
        if r.status_code in [200, 201]:
            print(
                f"  ✓ Upvoted: @{author}/{permlink} (Weight: {VOTE_WEIGHT}%)",
                flush=True,
            )
            return True
        else:
            print(
                f"  ❌ Vote response ({r.status_code}): {r.text[:150]}",
                flush=True,
            )
            return False
    except Exception as e:
        print(f"  ❌ Error voting: {e}", flush=True)
        return False


# ============================================================
# MAIN
# ============================================================


def main():
    print("=" * 60)
    print(f"SEREY AUTO VOTER -> RUNNING FOR @{SEREY_LOGIN}")
    print("=" * 60)

    init_file()
    voted_history = load_voted()
    print(f"Total previously voted posts: {len(voted_history)}", flush=True)

    posts = get_posts_to_vote()
    if not posts:
        print("No posts found to vote right now.", flush=True)
        return

    votes_given = 0

    for p in posts:
        if votes_given >= MAX_VOTES_PER_RUN:
            print(
                f"\n✓ Reached limit of {MAX_VOTES_PER_RUN} votes for this run.",
                flush=True,
            )
            break

        author = (
            p.get("author")
            or p.get("author_username")
            or p.get("author_name")
            or (p.get("author", {}) if isinstance(p.get("author"), dict) else {})
            .get("username")
        )
        permlink = p.get("permlink") or p.get("slug")

        if not author or not permlink:
            continue

        if str(author).lower() == SEREY_LOGIN.lower():
            continue

        post_id = f"{author}/{permlink}"
        if post_id in voted_history:
            continue

        print(
            f"\nVoting on ({votes_given + 1}/{MAX_VOTES_PER_RUN}): @{post_id}",
            flush=True,
        )
        success = cast_vote(author, permlink)

        if success:
            voted_history.add(post_id)
            save_voted(voted_history)
            votes_given += 1
            time.sleep(4)
        else:
            time.sleep(2)

    print("\n" + "=" * 60)
    print(f"AUTO VOTE COMPLETED. Total new votes given: {votes_given}")
    print("=" * 60)


if __name__ == "__main__":
    main()
