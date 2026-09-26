import os
import json
import time
import requests

# ============================================================
# SETTINGS & TOKEN FOR MAMUN
# ============================================================

SEREY_LOGIN = os.environ.get("SEREY_LOGIN", "mamun").replace("@", "").strip()

FALLBACK_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXBlIjoicG9zdGluZyIsInVzZXJuYW1lIjoibWFtdW4iLCJwYXNzd29yZCI6IjVLNDhVSEF1a3JuTkNHUGVxeTczUkRNTlRBbm1HRm1RY2I4MzRrZUxNSndCQnpkWWJLQyIsImlhdCI6MTc5MDQyOTg0OH0.v5tdje9uHEQ6ckavhtAgQxQHEaPIqji1H09Jvk2uiTk"
SEREY_TOKEN = os.environ.get("SEREY_TOKEN", FALLBACK_TOKEN).strip()

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
# FETCH POSTS
# ============================================================

def get_posts_to_vote():
    print("Fetching recent posts from Bengali Community...", flush=True)
    urls = [
        "https://global-api.serey.io/api/v2/post/list-by-trending?limit=25&offset=0&community_id=2",
        "https://global-api.serey.io/api/v2/post/list-by-created?limit=25&offset=0&community_id=2",
        "https://bengali.serey.io/api/posts?community_id=2"
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                # বিভিন্ন কী (keys) চেক করা
                posts = None
                if isinstance(data, dict):
                    posts = data.get("posts") or data.get("data") or data.get("result") or data.get("blogs")
                    if isinstance(posts, dict):
                        posts = posts.get("posts") or posts.get("data")
                elif isinstance(data, list):
                    posts = data

                if posts and isinstance(posts, list) and len(posts) > 0:
                    print(f"✓ Found {len(posts)} posts from API.", flush=True)
                    return posts
        except Exception as e:
            print(f"Fetch note ({url}): {e}", flush=True)
    return []

# ============================================================
# CAST VOTE
# ============================================================

def cast_vote(author, permlink):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "authorization": SEREY_TOKEN,
        "Origin": "https://bengali.serey.io",
        "Referer": "https://bengali.serey.io/blog"
    }

    payload = {
        "author": author,
        "permlink": permlink,
        "weight": VOTE_WEIGHT,
        "vote_type": "post"
    }

    try:
        r = requests.post(VOTE_API, json=payload, headers=headers, timeout=20)
        if r.status_code in [200, 201]:
            print(f"  ✓ Upvoted: @{author}/{permlink}", flush=True)
            return True
        else:
            print(f"  ❌ Vote response ({r.status_code}): {r.text[:100]}", flush=True)
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
            print(f"\n✓ Reached limit of {MAX_VOTES_PER_RUN} votes.", flush=True)
            break

        author = p.get("author") or p.get("author_username")
        permlink = p.get("permlink")

        if not author or not permlink:
            continue

        if author.lower() == SEREY_LOGIN.lower():
            continue

        post_id = f"{author}/{permlink}"
        if post_id in voted_history:
            continue

        print(f"\nVoting on ({votes_given + 1}/{MAX_VOTES_PER_RUN}): @{post_id}", flush=True)
        success = cast_vote(author, permlink)

        if success:
            voted_history.add(post_id)
            save_voted(voted_history)
            votes_given += 1
            time.sleep(4)
        else:
            time.sleep(2)

    print("\n" + "=" * 60)
    print(f"AUTO VOTE FINISHED. New votes: {votes_given}")
    print("=" * 60)

if __name__ == "__main__":
    main()
