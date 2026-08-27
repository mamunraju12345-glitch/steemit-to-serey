import os
import json
import requests
import time
import re
import urllib.parse
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()

PEXELS_API_KEY = os.environ.get(
    "PEXELS_API_KEY",
    ""
).strip()

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
TEMP_IMG_FILE = "temp_thumbnail.jpg"

# প্রতি রানে ১টি করে পোস্ট পাবলিশ করবে
POSTS_PER_RUN = 1


# ============================================================
# STEEM RPC
# ============================================================

def steem_rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }

    last_error = None

    for node in STEEM_NODES:

        try:

            print(
                f"Trying Steem RPC: {node}",
                flush=True
            )

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
                raise RuntimeError(
                    str(data["error"])
                )

            return data["result"]

        except Exception as e:

            last_error = e

            print(
                f"RPC failed: {node} -> {e}",
                flush=True
            )

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed. "
        f"Last error: {last_error}"
    )


# ============================================================
# SYNCED POSTS
# ============================================================

def load_synced_posts():

    if not os.path.exists(DATA_FILE):
        return set()

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):
            return set(data)

    except Exception as e:

        print(
            f"Could not read {DATA_FILE}: {e}",
            flush=True
        )

    return set()


def save_synced_posts(posts):

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sorted(posts),
            file,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# IMAGE + BODY CLEANING
# ============================================================

def extract_image_and_clean_body(
    body_text,
    json_metadata_str
):

    first_image_url = None

    try:

        meta = json.loads(
            json_metadata_str
        )

        if (
            isinstance(meta, dict)
            and
            isinstance(
                meta.get("image"),
                list
            )
            and
            meta["image"]
        ):

            first_image_url = (
                meta["image"][0]
            )

    except Exception:
        pass


    if not first_image_url:

        match = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
            body_text,
            re.IGNORECASE
        )

        if match:
            first_image_url = match.group(1)


    if not first_image_url:

        match = re.search(
            r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
            body_text,
            re.IGNORECASE
        )

        if match:
            first_image_url = match.group(0)


    clean_body = body_text


    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )


    clean_body = re.sub(
        r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
        '',
        clean_body,
        flags=re.IGNORECASE
    )


    clean_body = re.sub(
        r'\n\s*\n\s*\n+',
        '\n\n',
        clean_body
    )


    return (
        first_image_url,
        clean_body.strip()
    )


# ============================================================
# FETCH ALL STEEM POSTS (PECHON THEKE UPORER DIKE)
# ============================================================

def get_recent_posts():

    print(
        f"\nFetching ALL historical posts from Steemit: @{STEEM_USERNAME}",
        flush=True
    )

    all_posts = []
    seen_ids = set()

    start_author = None
    start_permlink = None
    page_number = 0

    while True:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author and start_permlink:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        page_number += 1

        print(
            f"Fetching Steemit batch #{page_number}...",
            flush=True
        )

        result = steem_rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        if start_author and start_permlink:
            batch = result[1:]
        else:
            batch = result

        if not batch:
            break

        added_this_batch = 0

        for post in batch:

            if post.get("author") != STEEM_USERNAME:
                continue

            author = post.get("author", "")
            permlink = post.get("permlink", "")

            if not permlink:
                continue

            post_id = f"{author}/{permlink}"

            if post_id in seen_ids:
                continue

            seen_ids.add(post_id)

            raw_body = post.get("body", "")
            metadata = post.get("json_metadata", "{}")

            image_url, clean_body = extract_image_and_clean_body(
                raw_body,
                metadata
            )

            all_posts.append({
                "author": author,
                "permlink": permlink,
                "title": post.get("title", ""),
                "body": clean_body,
                "image": image_url,
                "category": post.get("category", ""),
                "created": post.get("created", "")
            })

            added_this_batch += 1

        print(
            f"Batch #{page_number}: {len(result)} received, {added_this_batch} new posts. Total: {len(all_posts)}",
            flush=True
        )

        last_post = result[-1]
        new_start_author = last_post.get("author")
        new_start_permlink = last_post.get("permlink")

        if (
            new_start_author == start_author
            and
            new_start_permlink == start_permlink
        ):
            break

        if added_this_batch == 0:
            break

        start_author = new_start_author
        start_permlink = new_start_permlink

        if len(all_posts) >= 5000 or len(result) < 100:
            break

        time.sleep(0.3)

    # পেছনের পুরোনো পোস্ট থেকে শুরু হবে
    all_posts.reverse()

    print(
        f"\nTotal historical posts fetched: {len(all_posts)} (Oldest to Newest)",
        flush=True
    )

    return all_posts


# ============================================================
# DOWNLOAD IMAGE (ORIGINAL + PEXELS FALLBACK)
# ============================================================

def download_image(image_url, post_title=""):

    if image_url:
        try:

            print(
                f"Downloading original image: {image_url}",
                flush=True
            )

            response = requests.get(
                image_url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0"}
            )

            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()

            if "image" in content_type or len(response.content) > 1000:

                with open(TEMP_IMG_FILE, "wb") as file:
                    file.write(response.content)

                print("Image downloaded successfully!", flush=True)
                return TEMP_IMG_FILE

        except Exception as e:
            print(f"Original image download failed: {e}. Trying Pexels...", flush=True)

    try:
        clean_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', post_title).strip()
        words = [w for w in clean_query.split() if len(w) > 2][:3]
        keyword = " ".join(words) if words else "nature"

        fallback_url = None
        if PEXELS_API_KEY:
            try:
                p_url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(keyword)}&per_page=1"
                p_res = requests.get(p_url, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
                if p_res.status_code == 200:
                    p_data = p_res.json()
                    if p_data.get("photos") and len(p_data["photos"]) > 0:
                        fallback_url = p_data["photos"][0]["src"]["large"]
            except Exception:
                pass

        if not fallback_url:
            fallback_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(keyword)}?width=1080&height=720&nologo=true"

        print(f"Downloading Pexels/Free stock image: {fallback_url}", flush=True)
        response = requests.get(fallback_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()

        with open(TEMP_IMG_FILE, "wb") as file:
            file.write(response.content)

        print("Pexels/Free image downloaded successfully!", flush=True)
        return TEMP_IMG_FILE

    except Exception as e:
        print(f"Fallback download failed: {e}", flush=True)
        return None


# ============================================================
# NORMALIZE TEXT
# ============================================================

def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\u0980-\u09ff\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ============================================================
# 100% UPVOTE
# ============================================================

def cast_100_percent_vote(page):
    print("\n👍 GIVING 100% VOTE ON SEREY POST...", flush=True)
    try:
        page.wait_for_timeout(3000)

        vote_btn = page.locator(
            'span.anticon-like, '
            'i.anticon-like, '
            'button:has(.anticon-like), '
            'svg[data-icon="like"], '
            '.vote-btn, '
            '.like-btn, '
            'button:has-text("Upvote"), '
            'button:has-text("Like")'
        ).first

        if vote_btn.count() > 0:
            vote_btn.click(force=True)
            print("  - Vote button clicked!", flush=True)
            page.wait_for_timeout(2000)

            confirm_btn = page.locator(
                '.ant-modal-content button:has-text("Vote"), '
                '.ant-modal-content button:has-text("Confirm"), '
                '.ant-modal-footer button:has-text("OK"), '
                'button:has-text("Confirm Vote")'
            ).last

            if confirm_btn.count() > 0:
                confirm_btn.click(force=True)
                print("  - Confirmed 100% vote!", flush=True)

            page.wait_for_timeout(3000)
            print("✅ 100% VOTE GIVEN SUCCESSFULLY!", flush=True)
    except Exception as e:
        print(f"⚠️ Vote error: {e}", flush=True)


# ============================================================
# VERIFY SEREY POST
# ============================================================

def verify_serey_post(page, post):
    title = post["title"].strip()
    norm_title = normalize_text(title)

    print("\n🔎 VERIFYING POST ON SEREY...", flush=True)
    print(f"Expected title: {title}", flush=True)

    profile_urls = [
        f"https://serey.io/authors/{SEREY_LOGIN}",
        f"https://serey.io/authors/@{SEREY_LOGIN}"
    ]

    for profile_url in profile_urls:
        try:
            print(f"Checking profile: {profile_url}", flush=True)
            page.goto(profile_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)

            links = page.locator("a")
            for i in range(min(links.count(), 80)):
                try:
                    link = links.nth(i)
                    link_text = link.inner_text(timeout=500).strip()
                    if norm_title in normalize_text(link_text):
                        print(f"✅ POST TITLE FOUND LIVE ON PROFILE: {link_text}", flush=True)
                        link.click(force=True)
                        page.wait_for_timeout(4000)
                        cast_100_percent_vote(page)
                        return True
                except Exception:
                    continue

            if norm_title in normalize_text(page.content()):
                print("✅ POST FOUND IN PROFILE FEED!", flush=True)
                cast_100_percent_vote(page)
                return True

        except Exception as e:
            print(f"Profile check error: {e}", flush=True)

    print("❌ VERIFICATION FAILED.", flush=True)
    return False


# ============================================================
# PUBLISH TO SEREY
# ============================================================

def publish_to_serey(page, post):

    print(f"\n---> Publishing to Serey: {post['title']}", flush=True)

    try:
        page.goto("https://serey.io/blog/post/new", timeout=60000)
        page.wait_for_timeout(5000)

        # TITLE
        title_box = page.locator('input[placeholder*="title" i], input[placeholder*="Title"]').first
        title_box.fill(post["title"])
        print("  - Title filled!", flush=True)

        # BODY
        body_box = page.locator('div[contenteditable="true"], textarea[placeholder*="content" i], textarea').first
        body_box.fill(post["body"])
        print("  - Clean body content filled!", flush=True)
        page.wait_for_timeout(2000)

        # IMAGE (WITH PROCESSING WAIT)
        try:
            temp_image = download_image(post.get("image"), post.get("title", ""))
            if temp_image:
                file_input = page.locator('input[type="file"]').first
                if file_input.count() > 0:
                    file_input.set_input_files(temp_image)
                    print("  - Thumbnail uploaded! Waiting for server to process...", flush=True)
                    page.wait_for_timeout(8000)
        except Exception as e:
            print(f"  - Thumbnail skipped: {e}", flush=True)

        # FIRST PUBLISH
        page.locator('button:has-text("Publish")').first.click(force=True)
        print("  - First Publish button clicked!", flush=True)
        page.wait_for_timeout(5000)

        # CATEGORY
        try:
            dropdown = page.locator('.ant-select-selector, div:has-text("Select category"), input[placeholder*="category" i]').first
            dropdown.click(force=True)
            page.wait_for_timeout(2000)

            option = page.locator('.ant-select-item-option-content, .ant-select-item-option, div[title="Tech"], div[title="Crypto"], li').first
            if option.count() > 0:
                option.click(force=True)
            else:
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")

            print("  - Category selected successfully!", flush=True)
        except Exception as e:
            print(f"  - Category fallback: {e}", flush=True)
            page.keyboard.press("Tab")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")

        page.wait_for_timeout(3000)

        # FINAL PUBLISH
        final_publish = page.locator(
            '.ant-modal-content button:has-text("Publish"), '
            '.ant-modal-footer button:has-text("Publish"), '
            'button:has-text("Publish")'
        ).last

        final_publish.click(force=True)
        print("  - Final Publish button clicked! Waiting for blockchain broadcast...", flush=True)
        page.wait_for_timeout(15000)

        # REAL VERIFICATION
        verified = verify_serey_post(page, post)

        if verified:
            print(f"\n✅ VERIFIED & CONFIRMED ON PROFILE: {post['title']}", flush=True)
            return True

        print(f"\n❌ PUBLISH NOT VERIFIED: {post['title']}", flush=True)
        return False

    except Exception as e:
        print(f"\n❌ Failed to publish post on Serey: {e}", flush=True)
        return False

    finally:
        if os.path.exists(TEMP_IMG_FILE):
            try:
                os.remove(TEMP_IMG_FILE)
            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60, flush=True)
    print("       STEEMIT -> SEREY AUTOMATION", flush=True)
    print("=" * 60, flush=True)

    synced_posts = load_synced_posts()
    print(f"Previously synced posts: {len(synced_posts)}", flush=True)

    posts = get_recent_posts()

    new_posts = []
    for post in posts:
        post_id = f'{post["author"]}/{post["permlink"]}'
        if post_id not in synced_posts:
            new_posts.append(post)

    print(f"Total posts fetched: {len(posts)}", flush=True)
    print(f"Unsynced posts available: {len(new_posts)}", flush=True)

    new_posts_to_run = new_posts[:POSTS_PER_RUN]
    print(f"Publishing this run: {len(new_posts_to_run)} post(s)", flush=True)

    if not new_posts_to_run:
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

            page.locator('a:has-text("Log in"), button:has-text("Log in"), a:has-text("Log In"), button:has-text("Log In")').first.click(force=True)
            page.wait_for_timeout(5000)

            page.wait_for_selector('input[placeholder*="Username"]', timeout=20000)
            page.locator('input[placeholder*="Username"]').first.fill(SEREY_LOGIN)
            page.locator('input[placeholder*="Private Key"]').first.fill(SEREY_PASSWORD)
            page.locator('.ant-modal-content button:has-text("Log in"), button:has-text("Log in")').last.click(force=True)
            page.wait_for_timeout(6000)
            print("LOGGED INTO SEREY SUCCESSFULLY!", flush=True)

        except Exception as e:
            print(f"Login failed: {e}", flush=True)
            browser.close()
            return

        for post in new_posts_to_run:
            success = publish_to_serey(page, post)
            if success:
                post_id = f'{post["author"]}/{post["permlink"]}'
                synced_posts.add(post_id)
                save_synced_posts(synced_posts)
                print(f"✅ Saved as synced: {post_id}", flush=True)
            else:
                print("\n⚠️ Post was NOT verified.", flush=True)

        browser.close()

    print("\n" + "=" * 60, flush=True)
    print("SYNC COMPLETED", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
