import os
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"].replace("@", "").strip()

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()

SEREY = "https://serey.io"

NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"

# One post per GitHub Actions run
POSTS_PER_RUN = 1

# Only scan recent posts
DAYS_TO_SCAN = 60

# Maximum number of Steem API pages
MAX_PAGES = 10

# ============================================================
# STEEM RPC NODES
# ============================================================

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.moecki.online",
]

# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Steem-Serey-Sync/1.0",
    "Accept": "application/json",
})


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

    last_error = None

    for node in STEEM_NODES:

        try:

            print(
                f"RPC: {node}",
                flush=True
            )

            response = session.post(
                node,
                json=payload,
                timeout=(5, 15)
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                last_error = data["error"]

                print(
                    f"RPC error from {node}: {data['error']}",
                    flush=True
                )

                continue

            print(
                f"✓ RPC success: {node}",
                flush=True
            )

            return data["result"]

        except Exception as e:

            last_error = e

            print(
                f"RPC failed ({node}): {e}",
                flush=True
            )

    raise Exception(
        f"All Steem RPC nodes failed. Last error: {last_error}"
    )


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():

    if not os.path.exists(SYNC_FILE):
        return set()

    try:

        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, list):
            return set()

        return set(data)

    except Exception as e:

        print(
            f"⚠️ Could not read {SYNC_FILE}: {e}",
            flush=True
        )

        return set()


def save_synced(data):

    temp_file = SYNC_FILE + ".tmp"

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                sorted(data),
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            SYNC_FILE
        )

        print(
            f"✓ Sync file saved: {len(data)} posts",
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Failed to save sync file: {e}",
            flush=True
        )

        if os.path.exists(temp_file):

            try:
                os.remove(temp_file)
            except:
                pass


# ============================================================
# DATE PARSER
# ============================================================

def parse_steem_date(value):

    if not value:
        return None

    try:

        value = str(value).strip()

        # Steem normally returns:
        # 2026-09-18T10:20:30

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        # Make sure datetime is timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt

    except Exception:

        return None


# ============================================================
# CLEAN BODY + IMAGE
# ============================================================

def clean_post(body, metadata):

    image = None

    # --------------------------------------------------------
    # Try JSON metadata image
    # --------------------------------------------------------

    try:

        meta = json.loads(
            metadata or "{}"
        )

        images = meta.get(
            "image",
            []
        )

        if isinstance(images, list):

            for item in images:

                if isinstance(item, str):

                    if item.startswith("http"):

                        image = item
                        break

    except Exception:

        pass

    # --------------------------------------------------------
    # Try Markdown image
    # --------------------------------------------------------

    if not image:

        match = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)',
            body,
            re.I
        )

        if match:

            image = match.group(1)

    # --------------------------------------------------------
    # Remove Markdown images
    # --------------------------------------------------------

    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    # --------------------------------------------------------
    # Remove direct image URLs
    # --------------------------------------------------------

    body = re.sub(
        r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?',
        '',
        body,
        flags=re.I
    )

    # --------------------------------------------------------
    # Remove excessive blank lines
    # --------------------------------------------------------

    body = re.sub(
        r'\n{3,}',
        '\n\n',
        body
    )

    return body.strip(), image


# ============================================================
# GET RECENT STEEM POSTS
# ============================================================

def get_posts():

    print(
        f"Getting recent posts from @{STEEM_USERNAME}...",
        flush=True
    )

    posts = []

    seen = set()

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=DAYS_TO_SCAN)
    )

    start_author = None
    start_permlink = None

    previous_cursor = None

    for page_number in range(
        1,
        MAX_PAGES + 1
    ):

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:

            params["start_author"] = (
                start_author
            )

            params["start_permlink"] = (
                start_permlink
            )

        try:

            result = rpc(
                "condenser_api.get_discussions_by_blog",
                params
            )

        except Exception as e:

            print(
                f"❌ Failed to get Steem posts: {e}",
                flush=True
            )

            break

        if not result:

            print(
                "No more Steem results.",
                flush=True
            )

            break

        print(
            f"Steem page {page_number}: "
            f"{len(result)} results",
            flush=True
        )

        reached_cutoff = False

        for post in result:

            author = (
                post.get("author", "")
                or ""
            ).strip()

            permlink = (
                post.get("permlink", "")
                or ""
            ).strip()

            if not author or not permlink:
                continue

            post_id = (
                f"{author}/{permlink}"
            )

            if post_id in seen:
                continue

            seen.add(post_id)

            # Only our own posts
            if author != STEEM_USERNAME:
                continue

            created_raw = (
                post.get("created", "")
                or ""
            )

            created = parse_steem_date(
                created_raw
            )

            # Stop collecting old posts
            if created:

                if created < cutoff:

                    reached_cutoff = True
                    continue

            body, image = clean_post(
                post.get("body", ""),
                post.get(
                    "json_metadata",
                    "{}"
                )
            )

            posts.append({

                "id": post_id,

                "title": (
                    post.get("title", "")
                    or ""
                ).strip(),

                "body": body,

                "image": image,

                "category": (
                    post.get("category", "")
                    or ""
                ),

                "created": created_raw

            })

        # ----------------------------------------------------
        # Stop when 60-day limit reached
        # ----------------------------------------------------

        if reached_cutoff:

            print(
                f"✓ Reached {DAYS_TO_SCAN}-day cutoff.",
                flush=True
            )

            break

        # ----------------------------------------------------
        # Pagination cursor
        # ----------------------------------------------------

        last = result[-1]

        new_author = (
            last.get("author", "")
            or ""
        )

        new_permlink = (
            last.get("permlink", "")
            or ""
        )

        if not new_author or not new_permlink:

            print(
                "Pagination stopped: invalid cursor.",
                flush=True
            )

            break

        new_cursor = (
            f"{new_author}/{new_permlink}"
        )

        # Prevent infinite pagination loop
        if new_cursor == previous_cursor:

            print(
                "Pagination stopped: repeated cursor.",
                flush=True
            )

            break

        previous_cursor = new_cursor

        start_author = new_author
        start_permlink = new_permlink

        # Less than 100 means no more pages
        if len(result) < 100:

            break

        time.sleep(0.25)

    # --------------------------------------------------------
    # Oldest → newest
    # --------------------------------------------------------

    posts.sort(
        key=lambda x: (
            parse_steem_date(
                x.get("created", "")
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        )
    )

    print(
        f"✓ Recent posts found: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if not url:

        print(
            "No thumbnail image found.",
            flush=True
        )

        return None

    try:

        print(
            f"Downloading image: {url}",
            flush=True
        )

        response = session.get(
            url,
            timeout=(5, 20),
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        content_type = (
            response.headers
            .get("content-type", "")
            .lower()
        )

        if "image" not in content_type:

            print(
                f"⚠️ URL did not return an image: "
                f"{content_type}",
                flush=True
            )

            return None

        with open(
            TEMP_IMAGE,
            "wb"
        ) as f:

            f.write(
                response.content
            )

        print(
            "✓ Image downloaded.",
            flush=True
        )

        return TEMP_IMAGE

    except Exception as e:

        print(
            f"⚠️ Image download failed: {e}",
            flush=True
        )

        return None


# ============================================================
# SAFE CLICK HELPER
# ============================================================

def safe_click(
    page,
    selectors,
    name="button",
    timeout=3000
):

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            ).last

            if locator.is_visible(
                timeout=timeout
            ):

                locator.scroll_into_view_if_needed(
                    timeout=5000
                )

                locator.click(
                    force=True,
                    timeout=5000
                )

                print(
                    f"✓ Clicked {name}: {selector}",
                    flush=True
                )

                return True

        except Exception:
            continue

    return False


# ============================================================
# CLOSE IMAGE CROP MODAL
# ============================================================

def handle_crop_modal(page):

    print(
        "Checking image crop modal...",
        flush=True
    )

    # Ant Design image crop modal
    crop_selectors = [

        '.antd-img-crop-modal button:has-text("OK")',

        '.antd-img-crop-modal button:has-text("Confirm")',

        '.antd-img-crop-modal button:has-text("Done")',

        '.antd-img-crop-modal button:has-text("Save")',

        '.antd-img-crop-modal button:has-text("Apply")',

        '[role="dialog"] button:has-text("OK")',

        '[role="dialog"] button:has-text("Confirm")',

        '[role="dialog"] button:has-text("Done")',

        '[role="dialog"] button:has-text("Save")',

        '[role="dialog"] button:has-text("Apply")',

    ]

    if safe_click(
        page,
        crop_selectors,
        "crop confirmation",
        timeout=1500
    ):

        page.wait_for_timeout(
            3000
        )

        print(
            "✓ Image crop modal handled.",
            flush=True
        )

        return True

    # Sometimes modal has an X close button
    try:

        modal = page.locator(
            ".antd-img-crop-modal"
        )

        if modal.count() > 0:

            if modal.first.is_visible(
                timeout=1000
            ):

                close_selectors = [

                    '.antd-img-crop-modal button[aria-label="Close"]',

                    '.antd-img-crop-modal .ant-modal-close',

                    '.antd-img-crop-modal [aria-label="close"]',

                ]

                if safe_click(
                    page,
                    close_selectors,
                    "crop modal close",
                    timeout=1000
                ):

                    page.wait_for_timeout(
                        2000
                    )

                    return True

    except Exception:
        pass

    return False


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print(
        "Logging into Serey...",
        flush=True
    )

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        4000
    )

    # --------------------------------------------------------
    # Login trigger
    # --------------------------------------------------------

    login_selectors = [

        'a:has-text("Log in")',

        'button:has-text("Log in")',

        'a:has-text("Log In")',

        'button:has-text("Log In")',

    ]

    clicked = safe_click(
        page,
        login_selectors,
        "login button",
        timeout=5000
    )

    if not clicked:

        print(
            "⚠️ Login button not found.",
            flush=True
        )

    page.wait_for_timeout(
        3000
    )

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    username_selectors = [

        'input[placeholder*="Username"]',

        'input[placeholder*="username"]',

        'input[name="username"]',

        'input[type="text"]',

    ]

    username_box = None

    for selector in username_selectors:

        try:

            box = page.locator(
                selector
            ).first

            if box.is_visible(
                timeout=1500
            ):

                username_box = box
                break

        except:
            continue

    if not username_box:

        raise Exception(
            "Serey username input not found."
        )

    username_box.fill(
        SEREY_LOGIN
    )

    # --------------------------------------------------------
    # Private Key / Password
    # --------------------------------------------------------

    password_selectors = [

        'input[placeholder*="Private Key"]',

        'input[placeholder*="private key"]',

        'input[placeholder*="Password"]',

        'input[placeholder*="password"]',

        'input[type="password"]',

    ]

    password_box = None

    for selector in password_selectors:

        try:

            box = page.locator(
                selector
            ).first

            if box.is_visible(
                timeout=1500
            ):

                password_box = box
                break

        except:
            continue

    if not password_box:

        raise Exception(
            "Serey password/private-key input not found."
        )

    password_box.fill(
        SEREY_PASSWORD
    )

    # --------------------------------------------------------
    # Final login
    # --------------------------------------------------------

    if not safe_click(
        page,
        [
            'button:has-text("Log in")',
            'button:has-text("Log In")',
            'button[type="submit"]',
        ],
        "final login",
        timeout=3000
    ):

        raise Exception(
            "Serey final login button not found."
        )

    page.wait_for_timeout(
        7000
    )

    # --------------------------------------------------------
    # Verify login
    # --------------------------------------------------------

    current_url = page.url

    print(
        f"Login result URL: {current_url}",
        flush=True
    )

    if "/login" in current_url.lower():

        raise Exception(
            "Serey login appears to have failed."
        )

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )


# ============================================================
# VERIFY PUBLISHED POST
# ============================================================

def verify(page, title):

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    for attempt in range(1, 9):

        print(
            f"Verification attempt {attempt}/8",
            flush=True
        )

        page.wait_for_timeout(
            3000
        )

        current_url = page.url

        print(
            f"Current URL: {current_url}",
            flush=True
        )

        # ----------------------------------------------------
        # Author post URL
        # ----------------------------------------------------

        if (
            "/authors/" in current_url
            and "/blog/post/new" not in current_url
        ):

            print(
                "✓ SUCCESS: POST PUBLISHED!",
                flush=True
            )

            return True

        # ----------------------------------------------------
        # Success text
        # ----------------------------------------------------

        success_texts = [

            "Successfully posted your article",

            "Successfully posted",

            "Article published",

            "Post published",

            "Successfully published",

        ]

        for text_value in success_texts:

            try:

                if page.get_by_text(
                    text_value,
                    exact=False
                ).first.is_visible(
                    timeout=1000
                ):

                    print(
                        f"✓ SUCCESS MESSAGE: {text_value}",
                        flush=True
                    )

                    return True

            except:
                continue

        # ----------------------------------------------------
        # Look for author link
        # ----------------------------------------------------

        try:

            author_links = page.locator(
                'a[href*="/authors/"]'
            )

            if author_links.count() > 0:

                for i in range(
                    min(author_links.count(), 10)
                ):

                    href = author_links.nth(
                        i
                    ).get_attribute(
                        "href"
                    )

                    if href and "/authors/" in href:

                        print(
                            f"✓ Author post/profile URL detected: {href}",
                            flush=True
                        )

                        # Don't immediately assume profile is success
                        # unless it is a post-like author URL.
                        parts = href.strip("/").split("/")

                        if len(parts) >= 3:

                            print(
                                "✓ SUCCESS: Author post URL detected.",
                                flush=True
                            )

                            return True

        except:
            pass

    print(
        "❌ Publication could not be verified.",
        flush=True
    )

    return False


# ============================================================
# FIND PUBLISH BUTTON
# ============================================================

def click_first_publish(page):

    print(
        "Attempting first Publish button...",
        flush=True
    )

    publish_selectors = [

        'button:has-text("Publish")',

        'button:has-text("publish")',

        'div[role="button"]:has-text("Publish")',

        'span:has-text("Publish")',

    ]

    if safe_click(
        page,
        publish_selectors,
        "first Publish",
        timeout=3000
    ):

        return True

    # --------------------------------------------------------
    # JavaScript fallback
    # --------------------------------------------------------

    try:

        clicked = page.evaluate(
            """
            () => {

                const elements = Array.from(
                    document.querySelectorAll(
                        'button, div[role="button"], span'
                    )
                );

                const target = elements.find(
                    el =>
                        el.innerText &&
                        el.innerText.trim() === "Publish"
                );

                if (target) {

                    target.click();

                    return true;
                }

                return false;
            }
            """
        )

        if clicked:

            print(
                "✓ Publish clicked using JavaScript.",
                flush=True
            )

            return True

    except Exception as e:

        print(
            f"JavaScript publish click failed: {e}",
            flush=True
        )

    return False


# ============================================================
# FINAL PUBLISH / CONFIRMATION MODAL
# ============================================================

def handle_final_publish(page):

    print(
        "Checking Final Publish Modal...",
        flush=True
    )

    # --------------------------------------------------------
    # Wait briefly for modal
    # --------------------------------------------------------

    page.wait_for_timeout(
        3000
    )

    # --------------------------------------------------------
    # Final publish buttons
    # --------------------------------------------------------

    final_selectors = [

        'div[role="dialog"] button:has-text("Publish")',

        '.modal-content button:has-text("Publish")',

        '.modal button:has-text("Publish")',

        'div.fixed button:has-text("Publish")',

        'div[class*="modal"] button:has-text("Publish")',

        'div[class*="dialog"] button:has-text("Publish")',

        'div[role="dialog"] button:has-text("Confirm")',

        'div[role="dialog"] button:has-text("Submit")',

        'div[role="dialog"] button:has-text("Yes")',

        'button:has-text("Confirm")',

        'button:has-text("Submit")',

    ]

    if safe_click(
        page,
        final_selectors,
        "FINAL PUBLISH",
        timeout=2500
    ):

        print(
            "✓ FINAL PUBLISH CLICKED!",
            flush=True
        )

        page.wait_for_timeout(
            7000
        )

        return True

    print(
        "⚠️ No final Publish modal detected.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish(page, post):

    print(
        "-" * 60,
        flush=True
    )

    print(
        f"Publishing: {post['title']}",
        flush=True
    )

    print(
        f"Steem ID: {post['id']}",
        flush=True
    )

    print(
        f"Created: {post.get('created', '')}",
        flush=True
    )

    # --------------------------------------------------------
    # Open new post page
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        5000
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_selectors = [

        'input[placeholder*="Enter title"]',

        'input[placeholder*="Title"]',

        'input[name="title"]',

    ]

    title_box = None

    for selector in title_selectors:

        try:

            box = page.locator(
                selector
            ).first

            if box.is_visible(
                timeout=2000
            ):

                title_box = box
                break

        except:
            continue

    if not title_box:

        raise Exception(
            "Serey title input not found."
        )

    title_box.click()

    title_box.fill(
        post["title"]
    )

    print(
        "✓ Title filled.",
        flush=True
    )

    page.wait_for_timeout(
        1000
    )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    editor = page.locator(
        'div[contenteditable="true"]'
    ).first

    if not editor.is_visible(
        timeout=5000
    ):

        raise Exception(
            "Serey content editor not found."
        )

    editor.click()

    editor.fill(
        post["body"]
    )

    print(
        "✓ Body filled.",
        flush=True
    )

    page.wait_for_timeout(
        2000
    )

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

            if file_inputs.count() > 0:

                file_inputs.first.set_input_files(
                    image
                )

                print(
                    "✓ Thumbnail selected.",
                    flush=True
                )

                # Give Serey time to upload/process
                page.wait_for_timeout(
                    5000
                )

                # Important:
                # Serey image crop modal can block Publish
                handle_crop_modal(page)

                page.wait_for_timeout(
                    3000
                )

            else:

                print(
                    "⚠️ File input not found. "
                    "Continuing without thumbnail.",
                    flush=True
                )

        except Exception as e:

            print(
                f"⚠️ Thumbnail upload failed: {e}",
                flush=True
            )

    else:

        print(
            "⚠️ No image available. "
            "Publishing without thumbnail.",
            flush=True
        )

    # --------------------------------------------------------
    # Make sure crop modal is not blocking
    # --------------------------------------------------------

    handle_crop_modal(page)

    page.wait_for_timeout(
        1000
    )

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    if not click_first_publish(page):

        raise Exception(
            "Could not click first Publish button."
        )

    # --------------------------------------------------------
    # FINAL MODAL
    # --------------------------------------------------------

    handle_final_publish(page)

    # --------------------------------------------------------
    # Wait for navigation / publishing
    # --------------------------------------------------------

    page.wait_for_timeout(
        8000
    )

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    return verify(
        page,
        post["title"]
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60,
        flush=True
    )

    print(
        "STEEM -> SEREY AUTO SYNC",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    # --------------------------------------------------------
    # Load sync history
    # --------------------------------------------------------

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    # --------------------------------------------------------
    # Get recent posts
    # --------------------------------------------------------

    posts = get_posts()

    if not posts:

        print(
            "No recent Steem posts found.",
            flush=True
        )

        return

    # --------------------------------------------------------
    # Find unsynced
    # --------------------------------------------------------

    new_posts = [

        post

        for post in posts

        if post["id"] not in synced

    ]

    print(
        f"Unsynced recent posts: {len(new_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # One post per run
    # --------------------------------------------------------

    posts_to_run = new_posts[
        :POSTS_PER_RUN
    ]

    if not posts_to_run:

        print(
            "Nothing new to publish.",
            flush=True
        )

        return

    print(
        f"Posts selected for this run: "
        f"{len(posts_to_run)}",
        flush=True
    )

    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

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
                "Chrome/122.0.0.0 "
                "Safari/537.36"
            )

        )

        page = context.new_page()

        try:

            # ------------------------------------------------
            # Login once
            # ------------------------------------------------

            login(page)

            # ------------------------------------------------
            # Publish selected posts
            # ------------------------------------------------

            for post in posts_to_run:

                try:

                    success = publish(
                        page,
                        post
                    )

                    if success:

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
                            "⚠️ Publication was not verified.",
                            flush=True
                        )

                        print(
                            "⚠️ Post will NOT be added "
                            "to synced_posts.json.",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publish error: {e}",
                        flush=True
                    )

                    print(
                        "⚠️ This post will remain unsynced "
                        "for the next run.",
                        flush=True
                    )

        finally:

            # ------------------------------------------------
            # Cleanup
            # ------------------------------------------------

            if os.path.exists(
                TEMP_IMAGE
            ):

                try:
                    os.remove(
                        TEMP_IMAGE
                    )
                except:
                    pass

            try:
                context.close()
            except:
                pass

            try:
                browser.close()
            except:
                pass

    print(
        "=" * 60,
        flush=True
    )

    print(
        "SYNC COMPLETED",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
