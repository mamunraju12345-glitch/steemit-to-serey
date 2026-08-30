import os
import json
import re
import time
import requests
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

# Pexels API key is used ONLY as thumbnail fallback
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"

POSTS_PER_RUN = 1

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]


# ============================================================
# STEEM RPC
# ============================================================

def rpc(method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }

    for node in STEEM_NODES:
        try:
            print(f"RPC: {node}", flush=True)

            r = requests.post(
                node,
                json=payload,
                timeout=20
            )

            r.raise_for_status()
            data = r.json()

            if "error" in data:
                raise Exception(data["error"])

            return data["result"]

        except Exception as e:
            print(f"RPC failed: {e}", flush=True)

    raise Exception("All Steem RPC nodes failed")


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_synced(data):
    with open(
        SYNC_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            sorted(data),
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# CLEAN BODY + IMAGE
# ============================================================

def clean_post(body, metadata):
    image = None

    try:
        meta = json.loads(metadata or "{}")

        for x in meta.get("image", []):
            if isinstance(x, str):
                image = x
                break

    except Exception:
        pass

    if not image:
        m = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)',
            body,
            re.I
        )
        if m:
            image = m.group(1)

    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    body = re.sub(
        r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?',
        '',
        body,
        flags=re.I
    )

    body = re.sub(
        r'\n{3,}',
        '\n\n',
        body
    )

    return body.strip(), image


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():
    print(
        f"Getting posts from @{STEEM_USERNAME}...",
        flush=True
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None

    while len(posts) < 5000:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        batch = result[1:] if start_author else result

        if not batch:
            break

        for p in batch:

            if p.get("author") != STEEM_USERNAME:
                continue

            author = p.get("author", "")
            permlink = p.get("permlink", "")

            if not permlink:
                continue

            pid = f"{author}/{permlink}"

            if pid in seen:
                continue

            seen.add(pid)

            body, image = clean_post(
                p.get("body", ""),
                p.get("json_metadata", "{}")
            )

            posts.append({
                "id": pid,
                "title": p.get("title", "").strip(),
                "body": body,
                "image": image,
                "category": p.get("category", "")
            })

        last = result[-1]

        new_author = last.get("author")
        new_permlink = last.get("permlink")

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

        time.sleep(0.3)

    posts.reverse()

    print(
        f"Total posts: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if not url:
        return None

    try:
        print(
            f"Downloading image: {url}",
            flush=True
        )

        r = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        r.raise_for_status()

        if "image" not in r.headers.get(
            "content-type", ""
        ).lower():
            return None

        with open(TEMP_IMAGE, "wb") as f:
            f.write(r.content)

        return TEMP_IMAGE

    except Exception as e:
        print(
            f"Image download failed: {e}",
            flush=True
        )
        return None


# ============================================================
# PEXELS THUMBNAIL FALLBACK
# ============================================================

def download_pexels_image(title, category):

    if not PEXELS_API_KEY:
        print(
            "PEXELS_API_KEY not available.",
            flush=True
        )
        return None

    # Use the Steem post title first.
    # If title is too long, also include the category.
    query = title.strip()

    if category and category.lower() not in query.lower():
        query = f"{query} {category}"

    # Keep the search query reasonable.
    query = re.sub(r"\s+", " ", query).strip()
    query = query[:150]

    if not query:
        query = category.strip() or "photography"

    try:

        print(
            f"Pexels fallback search: {query}",
            flush=True
        )

        response = requests.get(
            "https://api.pexels.com/v1/search",
            headers={
                "Authorization": PEXELS_API_KEY
            },
            params={
                "query": query,
                "orientation": "landscape",
                "size": "large",
                "per_page": 1
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        photos = data.get("photos", [])

        if not photos:
            print(
                "No Pexels image found.",
                flush=True
            )
            return None

        photo = photos[0]

        image_url = (
            photo.get("src", {}).get("large")
            or photo.get("src", {}).get("original")
        )

        if not image_url:
            print(
                "Pexels image URL not found.",
                flush=True
            )
            return None

        print(
            f"Downloading Pexels image: {image_url}",
            flush=True
        )

        image_response = requests.get(
            image_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        image_response.raise_for_status()

        if "image" not in image_response.headers.get(
            "content-type",
            ""
        ).lower():
            print(
                "Pexels response is not an image.",
                flush=True
            )
            return None

        with open(TEMP_IMAGE, "wb") as f:
            f.write(image_response.content)

        print(
            "✓ Pexels thumbnail downloaded",
            flush=True
        )

        return TEMP_IMAGE

    except Exception as e:

        print(
            f"Pexels image failed: {e}",
            flush=True
        )

        return None


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print("Logging into Serey...", flush=True)

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    page.locator(
        'a:has-text("Log in"),'
        'button:has-text("Log in"),'
        'a:has-text("Log In"),'
        'button:has-text("Log In")'
    ).first.click(force=True)

    page.wait_for_timeout(3000)

    page.locator(
        'input[placeholder*="Username"]'
    ).first.fill(SEREY_LOGIN)

    page.locator(
        'input[placeholder*="Private Key"]'
    ).first.fill(SEREY_PASSWORD)

    page.locator(
        'button:has-text("Log in"),'
        'button:has-text("Log In")'
    ).last.click(force=True)

    page.wait_for_timeout(6000)

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )


# ============================================================
# CATEGORY
# ============================================================

def select_category(page, steem_category):

    print(
        f"Steemit category: {steem_category}",
        flush=True
    )

    try:

        text = page.locator("body").inner_text(
            timeout=5000
        )

        if "Your post belongs to category:" in text:
            print(
                "Serey suggested category automatically.",
                flush=True
            )

    except Exception:
        pass

    selector = page.get_by_text(
        "Select category",
        exact=True
    ).first

    if selector.count() == 0:
        print(
            "No category selector. Continuing.",
            flush=True
        )
        return False

    try:

        selector.click(force=True)

        page.wait_for_timeout(1000)

        option = page.get_by_text(
            steem_category,
            exact=True
        ).last

        if option.count() > 0 and option.is_visible():
            option.click(force=True)

            print(
                f"✓ Category selected: {steem_category}",
                flush=True
            )

            return True

        options = page.locator(
            '[role="option"]'
        )

        for i in range(options.count()):

            item = options.nth(i)

            if not item.is_visible():
                continue

            txt = item.inner_text().strip()

            if txt.lower() == steem_category.lower():

                item.click(force=True)

                print(
                    f"✓ Category selected: {txt}",
                    flush=True
                )

                return True

        print(
            f"Serey does not have category '{steem_category}'.",
            flush=True
        )

    except Exception as e:

        print(
            f"Category selection failed: {e}",
            flush=True
        )

    return False


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(page):

    try:

        selector = page.get_by_text(
            "Select sub category",
            exact=True
        ).first

        if selector.count() == 0:
            print(
                "No Sub Category selector.",
                flush=True
            )
            return

        selector.click(force=True)

        page.wait_for_timeout(800)

        options = page.locator(
            '[role="option"]'
        )

        if options.count() > 0:

            for i in range(options.count()):

                option = options.nth(i)

                if option.is_visible():
                    option.click(force=True)

                    print(
                        "✓ Sub Category selected.",
                        flush=True
                    )
                    return

        print(
            "No Sub Category available.",
            flush=True
        )

    except Exception as e:

        print(
            f"Sub Category skipped: {e}",
            flush=True
        )


# ============================================================
# VERIFY
# ============================================================

def verify(page, title):

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    for _ in range(3):

        page.wait_for_timeout(5000)

        url = page.url

        print(
            f"Current URL: {url}",
            flush=True
        )

        if "/blog/post/new" in url:
            continue

        if "/authors/" in url:

            print(
                "✓ POST URL FOUND!",
                flush=True
            )

            return True

        try:

            body = page.locator("body").inner_text()

            if title.lower() in body.lower():
                print(
                    "✓ POST TITLE FOUND!",
                    flush=True
                )
                return True

        except Exception:
            pass

    print(
        "❌ Publication could not be verified.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH
# ============================================================

def publish(page, post):

    print("-" * 60)
    print(
        f"Publishing: {post['title']}",
        flush=True
    )

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    # TITLE
    title = page.locator(
        'input[placeholder*="Title" i]'
    ).first

    title.fill(post["title"])

    print(
        "✓ Title filled",
        flush=True
    )

    # BODY
    editor = page.locator(
        'div[contenteditable="true"]'
    ).first

    editor.click()
    editor.fill(post["body"])

    print(
        "✓ Body filled",
        flush=True
    )

    # ========================================================
    # THUMBNAIL
    # ========================================================

    # First: use original Steemit image exactly as before.
    image = download_image(post.get("image"))

    # Only if original image is unavailable/download fails,
    # use Pexels as a fallback.
    if not image:

        print(
            "Original thumbnail unavailable.",
            flush=True
        )

        image = download_pexels_image(
            post.get("title", ""),
            post.get("category", "")
        )

    if image:

        try:

            file_input = page.locator(
                'input[type="file"]'
            ).first

            if file_input.count() > 0:

                file_input.set_input_files(
                    image
                )

                page.wait_for_timeout(3000)

                print(
                    "✓ Thumbnail uploaded",
                    flush=True
                )

        except Exception as e:

            print(
                f"Thumbnail skipped: {e}",
                flush=True
            )

    else:

        print(
            "No thumbnail available.",
            flush=True
        )

    # FIRST PUBLISH
    page.get_by_text(
        "Publish",
        exact=True
    ).last.click(force=True)

    print(
        "✓ FIRST PUBLISH CLICKED",
        flush=True
    )

    page.wait_for_timeout(3000)

    # CATEGORY
    select_category(
        page,
        post["category"]
    )

    # SUB CATEGORY
    select_subcategory(page)

    # FINAL PUBLISH
    print(
        "Searching for FINAL Publish...",
        flush=True
    )

    buttons = page.locator(
        "button"
    )

    final_button = None

    for i in range(buttons.count()):

        b = buttons.nth(i)

        if not b.is_visible():
            continue

        txt = b.inner_text().strip()

        if txt == "Publish":

            final_button = b

    if not final_button:

        print(
            "❌ FINAL Publish button not found.",
            flush=True
        )

        return False

    final_button.click(force=True)

    print(
        "✓ FINAL PUBLISH CLICKED",
        flush=True
    )

    page.wait_for_timeout(12000)

    return verify(
        page,
        post["title"]
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("STEEM -> SEREY AUTO SYNC")
    print("=" * 60)

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    posts = get_posts()

    new_posts = [
        p for p in posts
        if p["id"] not in synced
    ]

    print(
        f"Unsynced posts: {len(new_posts)}",
        flush=True
    )

    posts_to_run = new_posts[:POSTS_PER_RUN]

    print(
        f"Publishing this run: {len(posts_to_run)}",
        flush=True
    )

    if not posts_to_run:
        print("Nothing to publish.")
        return

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1280,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            login(page)

            for post in posts_to_run:

                try:

                    success = publish(
                        page,
                        post
                    )

                    if success:

                        synced.add(post["id"])
                        save_synced(synced)

                        print(
                            f"✓ SAVED AS SYNCED: {post['id']}",
                            flush=True
                        )

                    else:

                        print(
                            "⚠️ NOT SAVED AS SYNCED.",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publish error: {e}",
                        flush=True
                    )

        finally:

            if os.path.exists(TEMP_IMAGE):

                try:
                    os.remove(TEMP_IMAGE)
                except Exception:
                    pass

            browser.close()

    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
