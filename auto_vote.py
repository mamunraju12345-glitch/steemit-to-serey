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

# Bearer প্রিফিক্স নিশ্চিত করা
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
# FETCH POSTS (MULTIPLE ROBUST METHODS)
# ============================================================


def get_posts_to_vote():
    print("Fetching recent posts from Bengali Community...", flush=True)

    # মেথড ১: Serey Blockchain RPC Node (সবচেয়ে নির্ভরযোগ্য, ডাউন হয় না)
    rpc_nodes = ["https://rpc.serey.io", "https://api.serey.io"]
    for node in rpc_nodes:
        try:
            print(f"Trying Blockchain RPC: {node}...", flush=True)
            payload = {
                "jsonrpc": "2.0",
                "method": "condenser_api.get_discussions_by_created",
                "params": [{"tag": "bengali", "limit": 25}],
                "id": 1,
            }
            r = requests.post(node, json=payload, timeout=10)
            if r.status_code == 200:
                result = r.json().get("result", [])
                if result and len(result) > 0:
                    print(
                        f"✓ Found {len(result)} posts via Blockchain RPC!",
                        flush=True,
                    )
                    return result
        except Exception as e:
            print(f"RPC Error ({node}): {e}", flush=True)

    # মেথড ২: Serey Web GraphQL API
    try:
        print("Trying Serey GraphQL API...", flush=True)
        graphql_url = "https://global-api.serey.io/graphql"
        query = {
            "query": """
            query GetCommunityPosts {
                posts(community_id: 2, limit: 20, sort: "created") {
                    id
                    author
                    permlink
                    title
                }
            }
            """
        }
        r = requests.post(graphql_url, json=query, timeout=10)
        if r.status_code == 200:
            posts = r.json().get("data", {}).get("posts", [])
            if posts:
                print(
                    f"✓ Found {len(posts)} posts via GraphQL!", flush=True
                )
                return posts
    except Exception as e:
        print(f"GraphQL Error: {e}", flush=True)

    # মেথড ৩: Serey নতুন REST API
    rest_urls = [
        "https://global-api.serey.io/api/v1/posts?communityId=2&limit=20",
        "https://global-api.serey.io/post/getAllPosts?limit=20&community_id=2",
    ]
    for url in rest_urls:
        try:
            r = requests.get(url, timeout=10)
            print(
                f"Checking REST URL: {url} -> Status: {r.status_code}",
                flush=True,
            )
            if r.status_code == 200:
                data = r.json()
                posts = (
                    data.get("data")
                    if isinstance(data, dict)
                    else (data if isinstance(data, list) else None)
                )
                if posts and isinstance(posts, list) and len(posts) > 0:
                    print(
                        f"✓ Found {len(posts)} posts via REST API!", flush=True
                    )
                    return posts
        except Exception as e:
            print(f"REST error ({url}): {e}", flush=True)

    return []


# ============================================================
# CAST VOTE
# ============================================================


def cast_vote(author, permlink):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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

        # বিভিন্ন ধরনের রেসপন্স ফরম্যাট হ্যান্ডেল করা
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

        if author.lower() == SEREY_LOGIN.lower():
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
