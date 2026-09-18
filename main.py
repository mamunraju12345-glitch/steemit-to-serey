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

# Current Serey Bengali community
SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/write/new"

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

            print(f"✓ RPC success: {node}", flush=True)
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
            "content-type",
            ""
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
# LOGIN
# ============================================================

def login(page):

    print("Logging into Serey...", flush=True)

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    # Login trigger
    login_selectors = [
        'a:has-text("Log in")',
        'button:has-text("Log in")',
        'a:has-text("Log In")',
        'button:has-text("Log In")'
    ]

    clicked = False

    for selector in login_selectors:
        try:
            loc = page.locator(selector).first

            if loc.is_visible(timeout=3000):
                loc.click(force=True)
                clicked = True
                break

        except Exception:
            pass

    if not clicked:
        raise Exception("Serey login button not found.")

    page.wait_for_timeout(3000)

    # Username
    username_selectors = [
        'input[placeholder*="Username"]',
        'input[placeholder*="username"]',
        'input[name="username"]',
        'input[type="text"]'
    ]

    username_box = None

    for selector in username_selectors:
        try:
            loc = page.locator(selector).first

            if loc.is_visible(timeout=2000):
                username_box = loc
                break

        except Exception:
            pass

    if not username_box:
        raise Exception("Serey username input not found.")

    username_box.fill(SEREY_LOGIN)

    # Private key
    key_selectors = [
        'input[placeholder*="Private Key"]',
        'input[placeholder*="private key"]',
        'input[type="password"]'
    ]

    key_box = None

    for selector in key_selectors:
        try:
            loc = page.locator(selector).first

            if loc.is_visible(timeout=2000):
                key_box = loc
                break

        except Exception:
            pass

    if not key_box:
        raise Exception("Serey private key input not found.")

    key_box.fill(SEREY_PASSWORD)

    # Login submit
    submit_selectors = [
        'button:has-text("Log in")',
        'button:has-text("Log In")',
        'button[type="submit"]'
    ]

    submitted = False

    for selector in submit_selectors:
        try:
            loc = page.locator(selector).last

            if loc.is_visible(timeout=3000):
                loc.click(force=True)
                submitted = True
                break

        except Exception:
            pass

    if not submitted:
        raise Exception("Serey login submit button not found.")

    page.wait_for_timeout(8000)

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )


# ============================================================
# FIND TITLE INPUT
# ============================================================

def find_title_box(page):

    selectors = [
        'input[placeholder="Enter title..."]',
        'input[placeholder*="Enter title"]',
        'input[placeholder*="Title"]',
        'textarea[placeholder*="Enter title"]'
    ]

    for selector in selectors:

        try:
            loc = page.locator(selector).first

            if loc.is_visible(timeout=2500):
                return loc

        except Exception:
            pass

    return None


# ============================================================
# FIND CONTENT EDITOR
# ============================================================

def find_editor(page):

    selectors = [
        'textarea[placeholder="Enter content..."]',
        'textarea[placeholder*="Enter content"]',
        'div[contenteditable="true"]',
        '[contenteditable="true"]'
    ]

    for selector in selectors:

        try:
            loc = page.locator(selector).first

            if loc.is_visible(timeout=2500):
                return loc

        except Exception:
            pass

    return None


# ============================================================
# VERIFY
# ============================================================

def verify(page, title):

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    for _ in range(10):

        page.wait_for_timeout(3000)

        url = page.url

        print(
            f"Current URL: {url}",
            flush=True
        )

        # If we left the write page, publication may have succeeded
        if "/write/new" not in url:

            print(
                "✓ SUCCESS: Serey left the Write page.",
                flush=True
            )

            return True

        # Common success messages
        success_texts = [
            "Successfully posted",
            "Successfully published",
            "Article published",
            "Post published",
            "successfully posted your article"
        ]

        for text in success_texts:

            try:
                if page.get_by_text(
                    text,
                    exact=False
                ).is_visible(timeout=1000):

                    print(
                        f"✓ SUCCESS MESSAGE DETECTED: {text}",
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

    # --------------------------------------------------------
    # OPEN CURRENT SEREY WRITE PAGE
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    print(
        f"Write page: {page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_box = find_title_box(page)

    if not title_box:
        raise Exception(
            "Serey title input not found."
        )

    title_box.click()
    title_box.fill(post["title"])

    print(
        "✓ Title filled",
        flush=True
    )

    page.wait_for_timeout(1000)

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    editor = find_editor(page)

    if not editor:
        raise Exception(
            "Serey content editor not found."
        )

    editor.click()

    try:
        editor.fill(post["body"])
    except Exception:

        # Fallback for rich text editor
        page.keyboard.insert_text(post["body"])

    print(
        "✓ Body filled",
        flush=True
    )

    page.wait_for_timeout(2000)

    # --------------------------------------------------------
    # THUMBNAIL
    # --------------------------------------------------------

    image = download_image(
        post.get("image")
    )

    if image:

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            count = file_inputs.count()

            if count > 0:

                # Usually the first file input is thumbnail
                file_inputs.first.set_input_files(
                    image
                )

                print(
                    "✓ Thumbnail uploaded",
                    flush=True
                )

                page.wait_for_timeout(7000)

            else:

                print(
                    "⚠️ No file input found for thumbnail.",
                    flush=True
                )

        except Exception as e:

            print(
                f"⚠️ Thumbnail upload failed: {e}",
                flush=True
            )

    # --------------------------------------------------------
    # FIRST PUBLISH BUTTON
    # --------------------------------------------------------

    print(
        "Looking for Publish button...",
        flush=True
    )

    publish_selectors = [
        'button:has-text("Publish")',
        'button:has-text("publish")',
        '[role="button"]:has-text("Publish")',
        'button[type="submit"]'
    ]

    clicked = False

    for selector in publish_selectors:

        try:

            buttons = page.locator(selector)
            count = buttons.count()

            for i in range(count):

                btn = buttons.nth(i)

                if btn.is_visible(timeout=1000):

                    btn.scroll_into_view_if_needed()

                    btn.click(force=True)

                    print(
                        f"✓ Publish button clicked: {selector}",
                        flush=True
                    )

                    clicked = True
                    break

            if clicked:
                break

        except Exception:
            pass

    if not clicked:

        print(
            "Trying JavaScript Publish click...",
            flush=True
        )

        result = page.evaluate("""
        () => {
            const elements = Array.from(
                document.querySelectorAll(
                    'button, [role="button"]'
                )
            );

            const target = elements.find(el => {
                const text =
                    (el.innerText || el.textContent || '')
                    .trim()
                    .toLowerCase();

                return text === 'publish';
            });

            if (target) {
                target.click();
                return true;
            }

            return false;
        }
        """)

        if result:
            print(
                "✓ JavaScript Publish click executed",
                flush=True
            )
            clicked = True

    if not clicked:
        raise Exception(
            "Serey Publish button not found."
        )

    # --------------------------------------------------------
    # WAIT FOR MODAL / CONFIRMATION
    # --------------------------------------------------------

    page.wait_for_timeout(5000)

    print(
        "Checking for final confirmation...",
        flush=True
    )

    modal_selectors = [
        'div[role="dialog"] button:has-text("Publish")',
        'div[role="dialog"] button:has-text("Confirm")',
        'div[role="dialog"] button:has-text("Submit")',
        '[class*="modal"] button:has-text("Publish")',
        '[class*="modal"] button:has-text("Confirm")',
        '[class*="dialog"] button:has-text("Publish")',
        '[class*="dialog"] button:has-text("Confirm")'
    ]

    final_clicked = False

    for selector in modal_selectors:

        try:

            loc = page.locator(selector).last

            if loc.is_visible(timeout=1500):

                loc.click(force=True)

                print(
                    f"✓ Final confirmation clicked: {selector}",
                    flush=True
                )

                final_clicked = True
                break

        except Exception:
            pass

    if not final_clicked:

        print(
            "No confirmation modal detected.",
            flush=True
        )

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    page.wait_for_timeout(10000)

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

    if not posts_to_run:

        print(
            "Nothing to publish.",
            flush=True
        )

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
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
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

                    if publish(page, post):

                        synced.add(
                            post["id"]
                        )

                        save_synced(
                            synced
                        )

                        print(
                            f"✓ SAVED AS SYNCED: "
                            f"{post['id']}",
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

