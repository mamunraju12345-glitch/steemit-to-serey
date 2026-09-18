import os
import json
import re
import time
import requests

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ["SEREY_PASSWORD"].strip()

SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/write/new"

SYNC_FILE = "synced_posts.json"

POSTS_PER_RUN = 1

# Sync only posts from the last 365 days
DAYS_TO_SYNC = 365

# Temporary image files
IMAGE_PREFIX = "steem_image_"

# Steem RPC nodes
STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://api.steem.fans",
]


# ============================================================
# RPC
# ============================================================

def rpc(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    for node in STEEM_NODES:
        try:
            print(f"RPC: {node}")

            response = requests.post(
                node,
                json=payload,
                timeout=30,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Steem-Serey-Auto-Sync/1.0"
                }
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                print(f"RPC error from {node}: {data['error']}")
                continue

            print(f"✓ RPC success: {node}")
            return data.get("result")

        except Exception as e:
            print(f"RPC failed: {node}")
            print(f"Reason: {e}")

    raise RuntimeError("All Steem RPC nodes failed.")


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        if isinstance(data, dict):
            return set(data.keys())

    except Exception as e:
        print(f"Could not read {SYNC_FILE}: {e}")

    return set()


def save_synced(synced):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(list(synced)),
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def extract_images(post):
    """
    Extract image URLs from:
    1. Steem metadata
    2. Markdown images
    3. HTML <img src="">
    """

    images = []

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    try:
        metadata_raw = post.get("json_metadata", "{}")

        if isinstance(metadata_raw, str):
            metadata = json.loads(metadata_raw)
        else:
            metadata = metadata_raw

        if isinstance(metadata, dict):

            metadata_images = metadata.get("image", [])

            if isinstance(metadata_images, str):
                metadata_images = [metadata_images]

            if isinstance(metadata_images, list):
                for url in metadata_images:
                    if isinstance(url, str):
                        images.append(url)

    except Exception:
        pass

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    body = post.get("body", "") or ""

    # Markdown:
    # ![alt](https://example.com/image.jpg)
    markdown_images = re.findall(
        r'!\[[^\]]*\]\((https?://[^)\s]+)',
        body,
        flags=re.IGNORECASE
    )

    images.extend(markdown_images)

    # --------------------------------------------------------
    # HTML:
    # <img src="https://example.com/image.jpg">
    # --------------------------------------------------------

    html_images = re.findall(
        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
        body,
        flags=re.IGNORECASE
    )

    images.extend(html_images)

    # --------------------------------------------------------
    # Clean / unique
    # --------------------------------------------------------

    result = []

    for url in images:
        if not isinstance(url, str):
            continue

        url = url.strip()

        if not url.startswith(("http://", "https://")):
            continue

        if url not in result:
            result.append(url)

    return result


# ============================================================
# CLEAN POST
# ============================================================

def clean_post(body):
    """
    Keep the original body and images.

    We only reduce excessive blank lines.
    """

    if not body:
        return ""

    body = body.replace("\r\n", "\n")
    body = body.replace("\r", "\n")

    # Keep normal paragraph spacing
    body = re.sub(r"\n{4,}", "\n\n\n", body)

    return body.strip()


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():
    print(f"Getting posts from @{STEEM_USERNAME}...")
    print(f"Sync period: last {DAYS_TO_SYNC} days")

    # IMPORTANT:
    # timezone-aware UTC datetime
    now = datetime.now(timezone.utc)

    cutoff = now - timedelta(days=DAYS_TO_SYNC)

    print(f"Cutoff: {cutoff.isoformat()}")

    posts = []

    start_author = STEEM_USERNAME
    start_permlink = None

    page_number = 0

    while True:

        page_number += 1

        params = [{
            "tag": STEEM_USERNAME,
            "limit": 100,
            "start_author": start_author,
            "start_permlink": start_permlink
        }]

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        print(f"Steem page {page_number}: {len(result)} results")

        reached_cutoff = False

        for post in result:

            created = post.get("created", "")

            if not created:
                continue

            # ------------------------------------------------
            # FIX FOR:
            # can't compare offset-naive and offset-aware
            # datetimes
            # ------------------------------------------------

            try:
                created_dt = datetime.fromisoformat(
                    created.replace("Z", "+00:00")
                )

                # If Steem returns timezone-naive datetime,
                # treat it as UTC.
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(
                        tzinfo=timezone.utc
                    )

                # Convert everything to UTC
                created_dt = created_dt.astimezone(timezone.utc)

            except Exception as e:
                print(
                    f"Skipping post with invalid date "
                    f"{created}: {e}"
                )
                continue

            # ------------------------------------------------
            # Stop when posts become older than 365 days
            # ------------------------------------------------

            if created_dt < cutoff:
                reached_cutoff = True
                continue

            # ------------------------------------------------
            # Only user's own posts
            # ------------------------------------------------

            if post.get("author") != STEEM_USERNAME:
                continue

            # ------------------------------------------------
            # Build unique Steem post ID
            # ------------------------------------------------

            post_id = (
                f"{post.get('author')}/"
                f"{post.get('permlink')}"
            )

            post["_created_dt"] = created_dt
            post["_post_id"] = post_id

            posts.append(post)

        # ----------------------------------------------------
        # If the page contained posts older than cutoff,
        # no need to continue further back.
        # ----------------------------------------------------

        if reached_cutoff:
            break

        # ----------------------------------------------------
        # Pagination
        # ----------------------------------------------------

        last_post = result[-1]

        last_author = last_post.get("author")
        last_permlink = last_post.get("permlink")

        if not last_author or not last_permlink:
            break

        start_author = last_author
        start_permlink = last_permlink

        # Safety
        if len(result) < 100:
            break

    # --------------------------------------------------------
    # Sort oldest -> newest
    # --------------------------------------------------------

    posts.sort(
        key=lambda p: p["_created_dt"]
    )

    print()
    print(
        f"Total posts in last {DAYS_TO_SYNC} days: "
        f"{len(posts)}"
    )

    if posts:
        print(
            "Oldest:",
            posts[0]["_created_dt"].isoformat(),
            posts[0]["_post_id"]
        )

        print(
            "Newest:",
            posts[-1]["_created_dt"].isoformat(),
            posts[-1]["_post_id"]
        )

    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url, filename):
    try:
        print(f"Downloading image:")
        print(url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/130 Safari/537.36"
            )
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=30,
            stream=True
        )

        response.raise_for_status()

        content_type = (
            response.headers.get("content-type", "")
            .lower()
        )

        # ----------------------------------------------------
        # Some servers don't provide correct content-type.
        # We still allow common image extensions.
        # ----------------------------------------------------

        parsed = urlparse(url)
        path = parsed.path.lower()

        allowed_extension = (
            path.endswith(".jpg")
            or path.endswith(".jpeg")
            or path.endswith(".png")
            or path.endswith(".gif")
            or path.endswith(".webp")
            or path.endswith(".bmp")
            or path.endswith(".svg")
        )

        if "image/" not in content_type and not allowed_extension:
            print(
                f"Skipped non-image content: "
                f"{content_type}"
            )
            return None

        with open(filename, "wb") as f:

            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):
                if chunk:
                    f.write(chunk)

        size = os.path.getsize(filename)

        if size == 0:
            os.remove(filename)
            print("Downloaded file is empty.")
            return None

        print(
            f"✓ Image downloaded: "
            f"{filename} ({size} bytes)"
        )

        return filename

    except Exception as e:
        print(f"✗ Image download failed: {url}")
        print(f"Reason: {e}")

        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass

        return None


# ============================================================
# DOWNLOAD ALL IMAGES
# ============================================================

def download_all_images(image_urls):
    downloaded = []

    if not image_urls:
        print("No images found in post.")
        return downloaded

    print(
        f"Images found in post: "
        f"{len(image_urls)}"
    )

    for index, url in enumerate(image_urls, start=1):

        parsed = urlparse(url)

        extension = os.path.splitext(
            parsed.path
        )[1].lower()

        if extension not in [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".bmp",
            ".svg"
        ]:
            extension = ".jpg"

        filename = (
            f"{IMAGE_PREFIX}"
            f"{index}"
            f"{extension}"
        )

        result = download_image(
            url,
            filename
        )

        if result:
            downloaded.append(result)

    print(
        f"Downloaded images: "
        f"{len(downloaded)}/{len(image_urls)}"
    )

    return downloaded


# ============================================================
# SEREY LOGIN
# ============================================================

def login(page):

    print()
    print("Logging into Serey...")

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    time.sleep(3)

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    username_selectors = [
        'input[name="username"]',
        'input[name="login"]',
        'input[type="text"]',
        'input[placeholder*="username" i]',
        'input[placeholder*="email" i]'
    ]

    username_box = None

    for selector in username_selectors:
        try:
            locator = page.locator(selector)

            if locator.count() > 0:
                for i in range(locator.count()):
                    candidate = locator.nth(i)

                    if candidate.is_visible():
                        username_box = candidate
                        break

            if username_box:
                break

        except Exception:
            pass

    # --------------------------------------------------------
    # Password
    # --------------------------------------------------------

    password_box = None

    password_selectors = [
        'input[type="password"]',
        'input[name="password"]'
    ]

    for selector in password_selectors:
        try:
            locator = page.locator(selector)

            if locator.count() > 0:
                for i in range(locator.count()):
                    candidate = locator.nth(i)

                    if candidate.is_visible():
                        password_box = candidate
                        break

            if password_box:
                break

        except Exception:
            pass

    # --------------------------------------------------------
    # If login form is not directly visible,
    # click login/sign-in.
    # --------------------------------------------------------

    if not username_box or not password_box:

        login_buttons = [
            'text=Login',
            'text=Log in',
            'text=Sign in',
            'text=LOGIN',
            'text=LOG IN'
        ]

        for selector in login_buttons:
            try:
                locator = page.locator(selector)

                if locator.count() > 0:
                    for i in range(locator.count()):
                        candidate = locator.nth(i)

                        if candidate.is_visible():
                            candidate.click()
                            time.sleep(2)
                            break

                    break

            except Exception:
                pass

    # Try finding fields again
    if not username_box:

        for selector in username_selectors:
            try:
                locator = page.locator(selector)

                if locator.count() > 0:
                    for i in range(locator.count()):
                        candidate = locator.nth(i)

                        if candidate.is_visible():
                            username_box = candidate
                            break

                if username_box:
                    break

            except Exception:
                pass

    if not password_box:

        for selector in password_selectors:
            try:
                locator = page.locator(selector)

                if locator.count() > 0:
                    for i in range(locator.count()):
                        candidate = locator.nth(i)

                        if candidate.is_visible():
                            password_box = candidate
                            break

                if password_box:
                    break

            except Exception:
                pass

    if not username_box:
        raise RuntimeError(
            "Serey username input not found."
        )

    if not password_box:
        raise RuntimeError(
            "Serey password input not found."
        )

    username_box.fill(SEREY_LOGIN)
    password_box.fill(SEREY_PASSWORD)

    # --------------------------------------------------------
    # Submit
    # --------------------------------------------------------

    submit_selectors = [
        'button[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
        'input[type="submit"]'
    ]

    submitted = False

    for selector in submit_selectors:
        try:
            locator = page.locator(selector)

            if locator.count() > 0:

                for i in range(locator.count()):

                    candidate = locator.nth(i)

                    if candidate.is_visible():

                        candidate.click()

                        submitted = True

                        time.sleep(5)

                        break

            if submitted:
                break

        except Exception:
            pass

    if not submitted:
        password_box.press("Enter")
        time.sleep(5)

    # --------------------------------------------------------
    # Verify login
    # --------------------------------------------------------

    current_url = page.url

    print(f"After login URL: {current_url}")

    if "login" in current_url.lower():
        raise RuntimeError(
            "Serey login may have failed."
        )

    print("✓ LOGGED INTO SEREY SUCCESSFULLY!")


# ============================================================
# FIND TITLE BOX
# ============================================================

def find_title_box(page):

    print("Looking for Serey title field...")

    selectors = [
        'input[placeholder="Enter title..."]',
        'textarea[placeholder="Enter title..."]',
        'input[placeholder*="title" i]',
        'textarea[placeholder*="title" i]',
        'input[name="title"]',
        'textarea[name="title"]',
        '[contenteditable="true"]'
    ]

    # Wait for page/editor to appear
    try:
        page.wait_for_timeout(3000)
    except Exception:
        pass

    for selector in selectors:

        try:
            locator = page.locator(selector)

            count = locator.count()

            print(
                f"Checking selector: {selector} "
                f"-> {count}"
            )

            if count > 0:

                for i in range(count):

                    candidate = locator.nth(i)

                    try:

                        if candidate.is_visible():

                            print(
                                f"✓ Title field found: "
                                f"{selector}"
                            )

                            return candidate

                    except Exception:
                        pass

        except Exception as e:

            print(
                f"Selector error: "
                f"{selector} -> {e}"
            )

    # --------------------------------------------------------
    # Last attempt: inspect visible inputs
    # --------------------------------------------------------

    try:

        inputs = page.locator(
            "input, textarea"
        )

        count = inputs.count()

        print(
            f"Visible input/textarea count: {count}"
        )

        for i in range(count):

            candidate = inputs.nth(i)

            try:

                if not candidate.is_visible():
                    continue

                placeholder = candidate.get_attribute(
                    "placeholder"
                )

                name = candidate.get_attribute(
                    "name"
                )

                input_type = candidate.get_attribute(
                    "type"
                )

                print(
                    f"Field {i}: "
                    f"type={input_type}, "
                    f"name={name}, "
                    f"placeholder={placeholder}"
                )

            except Exception:
                pass

    except Exception as e:

        print(
            f"Could not inspect fields: {e}"
        )

    return Nonee


# ============================================================
# FIND EDITOR
# ============================================================

def find_editor(page):

    selectors = [
        'textarea[placeholder="Enter content..."]',
        'textarea[placeholder*="Enter content" i]',
        'textarea[name="content"]',
        'textarea[placeholder*="content" i]',
        '[contenteditable="true"]',
        '.ProseMirror'
    ]

    for selector in selectors:

        try:
            locator = page.locator(selector)

            if locator.count() > 0:

                for i in range(locator.count()):

                    candidate = locator.nth(i)

                    if candidate.is_visible():
                        return candidate

        except Exception:
            pass

    return None


# ============================================================
# TRY BODY IMAGE UPLOAD
# ============================================================

def try_upload_body_images(page, downloaded_images):

    if not downloaded_images:
        print(
            "No downloaded images available "
            "for body upload."
        )
        return

    try:

        file_inputs = page.locator(
            'input[type="file"]'
        )

        count = file_inputs.count()

        print(
            f"File inputs detected: {count}"
        )

        # ----------------------------------------------------
        # Usually the first file input is the thumbnail.
        # If there is only one, don't overwrite it with
        # every body image.
        # ----------------------------------------------------

        if count <= 1:

            print(
                "No separate inline image upload "
                "input detected."
            )

            print(
                "Original image URLs will remain "
                "inside the post body."
            )

            return

        # ----------------------------------------------------
        # Try additional file inputs for body images
        # ----------------------------------------------------

        for index, image_file in enumerate(
            downloaded_images,
            start=1
        ):

            input_index = index

            if input_index >= count:
                break

            try:

                file_inputs.nth(
                    input_index
                ).set_input_files(
                    image_file
                )

                print(
                    f"✓ Body image upload attempted: "
                    f"{image_file}"
                )

                time.sleep(1)

            except Exception as e:

                print(
                    f"Body image upload failed: "
                    f"{image_file}"
                )

                print(f"Reason: {e}")

    except Exception as e:

        print(
            "Inline body image upload check failed:"
        )

        print(e)

        print(
            "Original image URLs will remain "
            "in the body."
        )


# ============================================================
# VERIFY PUBLISH
# ============================================================
title_box = find_title_box(page)

if not title_box:
    raise RuntimeError(
        "Serey title input not found."
    )

title_box.fill(title)

print("✓ Title filled")
def verify(page):

    time.sleep(5)

    current_url = page.url

    print(
        f"After publish URL: {current_url}"
    )

    if current_url.rstrip("/") != NEW_POST.rstrip("/"):
        return True

    # Sometimes publish happens without immediate
    # redirect, so check for confirmation text.
    confirmation_texts = [
        "published",
        "success",
        "successfully",
        "post published"
    ]

    try:

        body_text = page.locator("body").inner_text(
            timeout=5000
        ).lower()

        for text_value in confirmation_texts:

            if text_value in body_text:
                return True

    except Exception:
        pass

    return False


# ============================================================
# PUBLISH TO SEREY
# ============================================================

def publish(page, post):

    title = post.get("title", "").strip()

    body = clean_post(
        post.get("body", "")
    )

    print()
    print("============================================================")
    print("Publishing post")
    print("============================================================")

    print(f"Title: {title}")
    print(
        f"Body length: {len(body)} characters"
    )

    # --------------------------------------------------------
    # Open new post page
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    time.sleep(4)

    print(
        f"Write page: {page.url}"
    )

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title_box = find_title_box(page)

    if not title_box:
        raise RuntimeError(
            "Serey title input not found."
        )

    title_box.fill(title)

    print("✓ Title filled")

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    editor = find_editor(page)

    if not editor:
        raise RuntimeError(
            "Serey content editor not found."
        )

    # --------------------------------------------------------
    # Preserve the body exactly as much as possible
    # --------------------------------------------------------

    try:

        tag_name = editor.evaluate(
            "(el) => el.tagName"
        )

        if tag_name.lower() == "textarea":

            editor.fill(body)

        else:

            editor.click()

            page.keyboard.insert_text(body)

    except Exception as e:

        print(
            f"Normal body fill failed: {e}"
        )

        try:
            editor.fill(body)
        except Exception:
            raise RuntimeError(
                "Could not fill Serey post body."
            )

    print("✓ Body filled")

    # --------------------------------------------------------
    # Extract images
    # --------------------------------------------------------

    image_urls = extract_images(post)

    # Remove duplicate URLs while keeping order
    image_urls = list(
        dict.fromkeys(image_urls)
    )

    print(
        f"Images found in post: "
        f"{len(image_urls)}"
    )

    # --------------------------------------------------------
    # Download images
    # --------------------------------------------------------

    downloaded_images = download_all_images(
        image_urls
    )

    # --------------------------------------------------------
    # Thumbnail
    # --------------------------------------------------------

    if downloaded_images:

        print(
            "Trying first downloaded image "
            "as Serey thumbnail..."
        )

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            count = file_inputs.count()

            if count > 0:

                file_inputs.nth(0).set_input_files(
                    downloaded_images[0]
                )

                print(
                    f"✓ Thumbnail upload attempted: "
                    f"{downloaded_images[0]}"
                )

                time.sleep(2)

            else:

                print(
                    "No thumbnail file input found."
                )

        except Exception as e:

            print(
                "Thumbnail upload failed:"
            )

            print(e)

    # --------------------------------------------------------
    # Body image upload
    # --------------------------------------------------------

    try_upload_body_images(
        page,
        downloaded_images
    )

    # --------------------------------------------------------
    # Publish button
    # --------------------------------------------------------

    publish_selectors = [
        'button:has-text("Publish")',
        'button:has-text("PUBLISH")',
        'button:has-text("Publish Post")',
        'button[type="submit"]'
    ]

    publish_button = None

    for selector in publish_selectors:

        try:

            locator = page.locator(selector)

            if locator.count() > 0:

                for i in range(locator.count()):

                    candidate = locator.nth(i)

                    if candidate.is_visible():

                        publish_button = candidate
                        break

            if publish_button:
                break

        except Exception:
            pass

    if not publish_button:

        raise RuntimeError(
            "Serey Publish button not found."
        )

    print("✓ Publish button found")

    publish_button.click()

    print(
        "✓ Publish button clicked"
    )

    time.sleep(3)

    # --------------------------------------------------------
    # Confirmation modal
    # --------------------------------------------------------

    confirm_selectors = [
        'button:has-text("Confirm")',
        'button:has-text("CONFIRM")',
        'button:has-text("Yes")',
        'button:has-text("Publish")'
    ]

    confirmed = False

    for selector in confirm_selectors:

        try:

            locator = page.locator(selector)

            if locator.count() > 0:

                for i in range(locator.count()):

                    candidate = locator.nth(i)

                    if candidate.is_visible():

                        # Don't accidentally click the
                        # original publish button again if
                        # no modal exists.
                        try:
                            candidate.click(
                                timeout=3000
                            )

                            confirmed = True

                            print(
                                "✓ Publish confirmation clicked"
                            )

                            time.sleep(5)

                            break

                        except Exception:
                            pass

            if confirmed:
                break

        except Exception:
            pass

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    if not verify(page):

        raise RuntimeError(
            "Could not verify Serey publication."
        )

    print(
        "✓ SEREY POST PUBLISHED SUCCESSFULLY!"
    )

    print(
        f"Final URL: {page.url}"
    )

    return page.url


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("============================================================")
    print("STEEM -> SEREY AUTO SYNC")
    print("============================================================")
    print()

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}"
    )

    # --------------------------------------------------------
    # Get posts
    # --------------------------------------------------------

    posts = get_posts()

    if not posts:

        print(
            "No posts found in the last "
            f"{DAYS_TO_SYNC} days."
        )

        return

    # --------------------------------------------------------
    # Filter unsynced
    # --------------------------------------------------------

    unsynced_posts = []

    for post in posts:

        post_id = post["_post_id"]

        if post_id not in synced:
            unsynced_posts.append(post)

    print()
    print(
        f"Unsynced posts: "
        f"{len(unsynced_posts)}"
    )

    if not unsynced_posts:

        print(
            "✓ All posts from the last "
            f"{DAYS_TO_SYNC} days are already synced."
        )

        return

    # --------------------------------------------------------
    # One post per run
    # --------------------------------------------------------

    selected_posts = unsynced_posts[
        :POSTS_PER_RUN
    ]

    print()
    print(
        f"Posts selected this run: "
        f"{len(selected_posts)}"
    )

    for post in selected_posts:

        print()
        print(
            "------------------------------------------------------------"
        )

        print(
            f"Selected: {post['_post_id']}"
        )

        print(
            f"Created: "
            f"{post['_created_dt'].isoformat()}"
        )

        print(
            f"Title: "
            f"{post.get('title', '')}"
        )

        print(
            "------------------------------------------------------------"
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
                "width": 1440,
                "height": 1000
            }
        )

        page = context.new_page()

        try:

            # ------------------------------------------------
            # Login
            # ------------------------------------------------

            login(page)

            # ------------------------------------------------
            # Publish selected post
            # ------------------------------------------------

            for post in selected_posts:

                post_id = post["_post_id"]

                try:

                    print()
                    print(
                        "Starting sync:"
                    )

                    print(post_id)

                    serey_url = publish(
                        page,
                        post
                    )

                    # ----------------------------------------
                    # Only mark synced after successful
                    # publication.
                    # ----------------------------------------

                    synced.add(post_id)

                    save_synced(synced)

                    print()
                    print(
                        f"✓ SAVED AS SYNCED: "
                        f"{serey_url}"
                    )

                except Exception as e:

                    print()
                    print(
                        f"✗ FAILED TO SYNC: "
                        f"{post_id}"
                    )

                    print(
                        f"Reason: {e}"
                    )

                    # Do NOT add failed post to synced
                    continue

        finally:

            context.close()
            browser.close()

    # --------------------------------------------------------
    # Cleanup downloaded images
    # --------------------------------------------------------

    print()
    print("Cleaning temporary images...")

    for filename in os.listdir("."):

        if filename.startswith(IMAGE_PREFIX):

            try:
                os.remove(filename)

                print(
                    f"Removed: {filename}"
                )

            except Exception:
                pass

    print()
    print("============================================================")
    print("RUN FINISHED")
    print("============================================================")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
