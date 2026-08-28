import os
import json
import requests
import time
import re
from datetime import datetime, timedelta, timezone
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

POSTS_PER_RUN = 1
START_FROM_DAYS_AGO = 2 * 365


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
# FETCH POSTS (STARTING AT 2 YEARS AGO)
# ============================================================

def get_recent_posts():

    print(
        f"\nFetching historical posts "
        f"from Steemit: @{STEEM_USERNAME}",
        flush=True
    )

    all_posts = []

    seen_ids = set()

    start_author = None
    start_permlink = None

    page_number = 0

    two_years_ago = datetime.now(timezone.utc) - timedelta(days=START_FROM_DAYS_AGO)
    stop_fetching = False

    while not stop_fetching:

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

        batch = result[1:] if (start_author and start_permlink) else result

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

            created_str = post.get("created", "")
            try:
                post_created_dt = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                post_created_dt = None

            if post_created_dt and post_created_dt < two_years_ago:
                stop_fetching = True
                break

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
                "created": created_str,
                "created_dt": post_created_dt
            })

            added_this_batch += 1

        if stop_fetching:
            break

        last_post = result[-1]

        new_start_author = last_post.get("author")
        new_start_permlink = last_post.get("permlink")

        if (
            new_start_author == start_author
            and
            new_start_permlink == start_permlink
        ):
            break

        if added_this_batch == 0 and not stop_fetching:
            break

        start_author = new_start_author
        start_permlink = new_start_permlink

        if len(all_posts) >= 5000 or len(result) < 100:
            break

        time.sleep(0.3)

    all_posts.sort(key=lambda x: x["created_dt"] if x["created_dt"] else datetime.min.replace(tzinfo=timezone.utc))

    print(
        f"\nTotal historical posts fetched: {len(all_posts)}",
        flush=True
    )

    return all_posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(image_url):

    if not image_url:
        return None

    try:
        print(f"Downloading image: {image_url}", flush=True)

        response = requests.get(
            image_url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        if "image" not in content_type:
            print("URL did not return an image.", flush=True)
            return None

        with open(TEMP_IMG_FILE, "wb") as file:
            file.write(response.content)

        print("Image downloaded successfully!", flush=True)
        return TEMP_IMG_FILE

    except Exception as e:
        print(f"Image download failed: {e}", flush=True)
        return None


# ============================================================
# NORMALIZE TITLE FOR VERIFICATION
# ============================================================

def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\u0980-\u09ff\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ============================================================
# VERIFY SEREY POST
# ============================================================

def verify_serey_post(page, post):

    title = post["title"].strip()

    print("\n🔎 VERIFYING POST ON SEREY...", flush=True)
    print(f"Expected title: {title}", flush=True)

    page.wait_for_timeout(4000)
    current_url = page.url
    print(f"Current Serey URL: {current_url}", flush=True)

    if "/blog/post/new" in current_url:
        print("❌ FAILED: Browser is still on creation page (/blog/post/new). Form did not submit!", flush=True)
        return False

    profile_urls = [
        f"https://serey.io/authors/@{SEREY_LOGIN}",
        f"https://serey.io/authors/{SEREY_LOGIN}"
    ]

    normalized_title = normalize_text(title)

    for profile_url in profile_urls:
        try:
            print(f"Checking profile: {profile_url}", flush=True)
            page.goto(profile_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            profile_html = page.content()
            normalized_profile = normalize_text(profile_html)

            if normalized_title and normalized_title in normalized_profile:
                print("✅ POST TITLE FOUND ON SEREY PROFILE!", flush=True)
                print(f"Verified URL: {profile_url}", flush=True)
                return True

        except Exception as e:
            print(f"Profile verification error: {e}", flush=True)

    print("❌ VERIFICATION FAILED. Post was not confirmed live on Serey.", flush=True)
    return False


# ============================================================
# PUBLISH TO SEREY (FIXED CATEGORY POPUP CLICK)
# ============================================================

def publish_to_serey(page, post):

    print(f"\n---> Publishing to Serey: {post['title']}", flush=True)

    try:
        page.goto("https://serey.io/blog/post/new", timeout=60000)
        page.wait_for_timeout(4000)

        # TITLE
        title_box = page.locator(
            'input[placeholder*="title" i], input[placeholder*="Title"]'
        ).first
        title_box.focus()
        title_box.fill(post["title"])
        title_box.dispatch_event("input")
        print("  - Title filled!", flush=True)

        # BODY
        body_box = page.locator(
            'div[contenteditable="true"], textarea[placeholder*="content" i], textarea'
        ).first
        body_box.focus()
        body_box.fill(post["body"])
        body_box.dispatch_event("input")
        print("  - Clean body content filled!", flush=True)

        page.wait_for_timeout(2000)

        # IMAGE
        if post.get("image"):
            try:
                temp_image = download_image(post["image"])
                if temp_image:
                    file_input = page.locator('input[type="file"]').first
                    if file_input.count() > 0:
                        file_input.set_input_files(temp_image)
                        print("  - Thumbnail image uploaded!", flush=True)
                        page.wait_for_timeout(4000)
            except Exception as e:
                print(f"  - Thumbnail upload skipped: {e}", flush=True)

        # FIRST PUBLISH CLICK
        print("  - Clicking initial Publish button...", flush=True)
        page.locator('button:has-text("Publish")').first.click(force=True)
        page.wait_for_timeout(4000)

        # CATEGORY SELECTION (DIRECT DROPDOWN POPUP CLICK)
        print("  - Selecting Category...", flush=True)
        try:
            # Click modal dropdown box
            modal_select = page.locator('.ant-modal-body .ant-select, .ant-modal .ant-select-selector').first
            modal_select.click(force=True)
            page.wait_for_timeout(1500)

            # Find visible popup option in DOM
            dropdown_popup = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
            if dropdown_popup.count() > 0 and dropdown_popup.is_visible():
                opt = dropdown_popup.locator('.ant-select-item-option').first
                opt.click(force=True)
                print("  - Category option clicked directly from popup!", flush=True)
            else:
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
                print("  - Category selected via keyboard fallback!", flush=True)
        except Exception as cat_err:
            print(f"  - Category select error: {cat_err}", flush=True)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")

        page.wait_for_timeout(2000)

        # FINAL PUBLISH CLICK IN MODAL
        print("  - Clicking Final Publish button in Modal...", flush=True)
        modal_btn = page.locator(
            '.ant-modal-content button:has-text("Publish"), .ant-modal-footer button:has-text("Publish")'
        ).last
        modal_btn.click(force=True)

        page.wait_for_timeout(3000)

        # CHECK FOR SEREY ERROR TOAST
        error_notice = page.locator('.ant-message-error, .ant-notification-notice-error').first
        if error_notice.count() > 0 and error_notice.is_visible():
            print(f"  - SEREY SCREEN ERROR: {error_notice.inner_text()}", flush=True)

        print("  - Final Publish button clicked! Waiting for page redirect...", flush=True)

        # Wait up to 15s for redirect away from /blog/post/new
        for _ in range(15):
            page.wait_for_timeout(1000)
            if "/blog/post/new" not in page.url:
                print(f"  - Redirected successfully to: {page.url}", flush=True)
                break

        # VERIFICATION
        verified = verify_serey_post(page, post)
        return verified

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

    print(f"Total historical posts (Within last 2 years): {len(posts)}", flush=True)
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

            print("Clicking Log in button...", flush=True)
            page.locator(
                'a:has-text("Log in"), button:has-text("Log in"), a:has-text("Log In"), button:has-text("Log In")'
            ).first.click(force=True)

            page.wait_for_timeout(5000)

            page.wait_for_selector(
                'input[placeholder="Username"], input[placeholder*="Username"]',
                timeout=20000
            )

            page.locator(
                'input[placeholder="Username"], input[placeholder*="Username"]'
            ).first.fill(SEREY_LOGIN)

            page.locator(
                'input[placeholder="Private Key or Password"], input[placeholder*="Private Key"]'
            ).first.fill(SEREY_PASSWORD)

            page.locator(
                '.ant-modal-content button:has-text("Log in"), .ant-modal-content button:has-text("Log In"), button:has-text("Log in")'
            ).last.click(force=True)

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
                print("It will remain unsynced and can be retried on the next run.", flush=True)

        browser.close()

    print("\n" + "=" * 60, flush=True)
    print("SYNC COMPLETED", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
