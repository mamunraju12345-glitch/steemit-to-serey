import os
import json
import time
import re
import requests

from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# STEEMIT → BENGALI SEREY AUTO SYNC
# ============================================================

STEEM_API = "https://api.steemit.com"
SEREY_URL = "https://bengali.serey.io"

STEEM_USERNAME = os.getenv("STEEM_USERNAME")
SEREY_USERNAME = os.getenv("SEREY_USERNAME")
SEREY_PASSWORD = os.getenv("SEREY_PASSWORD")

SYNC_FILE = "synced_posts.json"

# User requested: oldest 1000 posts only
OLDEST_POST_LIMIT = 1000

# One post per GitHub Actions run
POSTS_PER_RUN = 1


# ============================================================
# PERMANENTLY SKIPPED POSTS
# ============================================================

PERMANENT_SKIP = {
    "mamun123456/-4ac8aa756c94d",
    "mamun123456/-709cad84fe936",
    "mamun123456/-c03668de5eadb",
    "mamun123456/7b7def53-7953-11e8-ac3d-0242ac110003",
    "mamun123456/being-a-good-man-and-being-a-bad-person-is-easy-method-3a94ff5da598",
    "mamun123456/c4lw147p",
    "mamun123456/cf30d320-7a61-11e8-827c-49f76fdbeab3",
    "mamun123456/coconut-water-has-many-advantages",
    "mamun123456/my-little-brother-photography-and-some-story-55445d86075ec",
    "mamun123456/vh2aqw72",
    "mamun123456/what-should-we-do-if-jaundice-96b00cbcf18c8",
}


# ============================================================
# BASIC CHECK
# ============================================================

def check_environment():
    print("=" * 60)
    print("SEREY AUTO SYNC")
    print("=" * 60)

    if not STEEM_USERNAME:
        print("❌ STEEM_USERNAME is missing.")
        return False

    if not SEREY_USERNAME:
        print("❌ SEREY_USERNAME is missing.")
        return False

    if not SEREY_PASSWORD:
        print("❌ SEREY_PASSWORD is missing.")
        return False

    print(f"Steem username : {STEEM_USERNAME}")
    print(f"Serey username : {SEREY_USERNAME}")
    print("✓ Environment variables OK")

    return True


# ============================================================
# SYNCED POSTS FILE
# ============================================================

def load_synced_posts():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(str(x) for x in data)

        return set()

    except Exception as e:
        print(f"⚠️ Could not read {SYNC_FILE}: {e}")
        return set()


def save_synced_posts(synced_posts):
    try:
        data = sorted(list(synced_posts))

        with open(SYNC_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"✓ SAVED AS SYNCED: {len(data)} total")

    except Exception as e:
        print(f"❌ Failed saving synced posts: {e}")


# ============================================================
# STEEM API
# ============================================================

def steem_api_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }

    response = requests.post(
        STEEM_API,
        json=payload,
        timeout=60
    )

    response.raise_for_status()

    result = response.json()

    if "error" in result:
        raise Exception(result["error"])

    return result.get("result")


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_all_steem_posts():
    print("\n========================================")
    print("COLLECTING STEEM POSTS")
    print("========================================")

    posts = []

    start_author = STEEM_USERNAME
    start_permlink = ""

    page = 0

    while True:
        page += 1

        try:
            result = steem_api_call(
                "condenser_api.get_discussions_by_blog",
                [{
                    "tag": start_author,
                    "limit": 100,
                    "start_author": start_author,
                    "start_permlink": start_permlink
                }]
            )

        except Exception as e:
            print(f"❌ Steem API error on page {page}: {e}")
            break

        if not result:
            break

        print(f"Steem page {page}: {len(result)} posts")

        for post in result:

            author = post.get("author", "")
            permlink = post.get("permlink", "")

            # Only user's own posts
            if author != STEEM_USERNAME:
                continue

            # Only root posts
            if post.get("parent_author"):
                continue

            # Ignore deleted/empty posts
            if not post.get("title"):
                continue

            posts.append(post)

        if len(result) < 100:
            break

        last = result[-1]

        start_author = last.get("author")
        start_permlink = last.get("permlink")

        if not start_author or not start_permlink:
            break

        time.sleep(0.2)

    print(f"\nTotal posts: {len(posts)}")

    # Newest → oldest from Steem API.
    # Reverse to oldest → newest.
    posts.reverse()

    return posts


# ============================================================
# POST KEY
# ============================================================

def get_post_key(post):
    author = post.get("author", "")
    permlink = post.get("permlink", "")

    return f"{author}/{permlink}"


# ============================================================
# HTML CLEANING
# ============================================================

def clean_body(body):
    if not body:
        return ""

    # Remove dangerous script tags
    body = re.sub(
        r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>",
        "",
        body,
        flags=re.IGNORECASE
    )

    return body.strip()


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def extract_image_url(body):
    if not body:
        return None

    patterns = [
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'(https?://cdn\.steemitimages\.com/[^\s"\')]+)',
        r'(https?://steemitimages\.com/[^\s"\')]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)

        if match:
            url = match.group(1)

            if url.startswith("http"):
                return url

    return None


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(image_url):
    if not image_url:
        print("No thumbnail available.")
        return None

    print(f"Downloading image: {image_url}")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        }

        response = requests.get(
            image_url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "content-type",
            ""
        ).lower()

        if "image" not in content_type:
            print(
                f"⚠️ URL did not return an image. "
                f"Content-Type: {content_type}"
            )
            return None

        extension = ".jpg"

        if "png" in content_type:
            extension = ".png"
        elif "webp" in content_type:
            extension = ".webp"
        elif "gif" in content_type:
            extension = ".gif"

        filename = f"steem_thumbnail{extension}"

        with open(filename, "wb") as f:
            f.write(response.content)

        print(f"✓ Image downloaded: {filename}")

        return filename

    except Exception as e:
        print(f"⚠️ Image attempt failed: {e}")
        print("⚠️ Image unavailable. Continuing without image.")
        return None


# ============================================================
# LOGIN
# ============================================================

def login_serey(page):

    print("\nLogging into Serey...")

    page.goto(
        f"{SEREY_URL}/login",
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    # Email / username
    inputs = page.locator("input")

    count = inputs.count()

    if count < 2:
        print("❌ Login inputs not found.")
        return False

    try:
        inputs.nth(0).fill(SEREY_USERNAME)
        inputs.nth(1).fill(SEREY_PASSWORD)
    except Exception as e:
        print(f"❌ Could not fill login form: {e}")
        return False

    # Login button
    buttons = page.locator("button")

    clicked = False

    for i in range(buttons.count()):
        try:
            text = buttons.nth(i).inner_text().strip().lower()

            if "login" in text or "sign in" in text:
                buttons.nth(i).click()
                clicked = True
                break

        except Exception:
            continue

    if not clicked:
        print("❌ Login button not found.")
        return False

    page.wait_for_timeout(5000)

    current_url = page.url

    if "/login" not in current_url.lower():
        print("✓ SEREY LOGIN VERIFIED!")
        return True

    # Check page text as secondary verification
    try:
        body_text = page.locator("body").inner_text().lower()

        if "logout" in body_text or SEREY_USERNAME.lower() in body_text:
            print("✓ SEREY LOGIN VERIFIED!")
            return True

    except Exception:
        pass

    print("❌ SEREY LOGIN FAILED.")
    return False


# ============================================================
# FIND VISIBLE PUBLISH BUTTONS
# ============================================================

def get_visible_publish_buttons(page):

    result = []

    buttons = page.locator("button")

    for i in range(buttons.count()):

        try:
            button = buttons.nth(i)

            if not button.is_visible():
                continue

            text = button.inner_text().strip()

            if text.lower() == "publish":
                result.append(button)

        except Exception:
            continue

    return result


# ============================================================
# IMAGE CROP MODAL
# ============================================================

def handle_image_crop_modal(page):

    try:
        modal = page.locator(
            ".antd-img-crop-modal:visible"
        )

        if modal.count() == 0:
            return True

        print("Image crop modal detected.")

        # Try OK first
        buttons = modal.locator("button")

        for i in range(buttons.count()):

            try:
                button = buttons.nth(i)

                if not button.is_visible():
                    continue

                text = button.inner_text().strip().lower()

                if text in ("ok", "crop", "confirm", "done"):
                    button.click()
                    page.wait_for_timeout(1000)

                    print("✓ Image crop confirmed.")
                    return True

            except Exception:
                continue

        # Last visible button fallback
        visible_buttons = []

        for i in range(buttons.count()):

            try:
                if buttons.nth(i).is_visible():
                    visible_buttons.append(buttons.nth(i))
            except Exception:
                pass

        if visible_buttons:
            visible_buttons[-1].click()
            page.wait_for_timeout(1000)

            print("✓ Image crop modal closed.")
            return True

    except Exception as e:
        print(f"⚠️ Image crop handling error: {e}")

    return True


# ============================================================
# CATEGORY HANDLING
# ============================================================

def handle_category(page, category):

    print(f"Steemit category: {category}")

    # Serey often automatically detects category.
    # We intentionally do NOT force an unknown selector.

    try:
        text = page.locator("body").inner_text().lower()

        if "category" in text:
            print("Category information detected.")

    except Exception:
        pass

    print("No category selector. Continuing.")


# ============================================================
# CATEGORY CONFIRMATION MODAL
# ============================================================

def click_category_confirmation_publish(page):

    print("Searching for Serey Publish confirmation...")

    for attempt in range(15):

        try:
            modals = page.locator(
                ".ant-modal-wrap:visible"
            )

            if modals.count() > 0:

                modal = modals.last

                text = ""

                try:
                    text = modal.inner_text().strip()
                except Exception:
                    pass

                print("Checking Serey confirmation modal...")

                if text:
                    print("Serey modal detected:")
                    print(text)

                buttons = modal.locator("button")

                publish_buttons = []

                for i in range(buttons.count()):

                    try:
                        button = buttons.nth(i)

                        if not button.is_visible():
                            continue

                        button_text = (
                            button.inner_text()
                            .strip()
                            .lower()
                        )

                        if button_text == "publish":
                            publish_buttons.append(button)

                    except Exception:
                        continue

                if publish_buttons:

                    print(
                        "✓ Publish button found inside "
                        f"Serey modal: {len(publish_buttons)}"
                    )

                    publish_buttons[-1].click()

                    page.wait_for_timeout(1500)

                    # IMPORTANT:
                    # This Publish only confirms category.
                    # It is NOT the final publication.
                    for _ in range(20):

                        try:
                            if page.locator(
                                ".ant-modal-wrap:visible"
                            ).count() == 0:

                                print(
                                    "✓ Category confirmation "
                                    "modal closed."
                                )

                                return True

                        except Exception:
                            pass

                        page.wait_for_timeout(300)

                    print(
                        "⚠️ Category modal did not disappear "
                        "immediately."
                    )

                    return True

        except Exception as e:
            print(
                f"⚠️ Category modal check "
                f"{attempt + 1}: {e}"
            )

        page.wait_for_timeout(500)

    # Sometimes there is no confirmation modal.
    print("No Serey confirmation modal found.")

    return True


# ============================================================
# FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    print("\nSearching for FINAL Publish...")

    # Give category confirmation time to disappear.
    page.wait_for_timeout(1000)

    # Do NOT blindly close any modal here.
    # Only continue after the category modal is gone.

    for attempt in range(20):

        try:

            # If category modal still exists, wait.
            if page.locator(
                ".ant-modal-wrap:visible"
            ).count() > 0:

                page.wait_for_timeout(500)
                continue

            publish_buttons = get_visible_publish_buttons(page)

            print(
                f"Visible Publish buttons: "
                f"{len(publish_buttons)}"
            )

            if publish_buttons:

                # The main page final Publish is normally the
                # last visible Publish button.
                button = publish_buttons[-1]

                try:
                    button.scroll_into_view_if_needed()
                except Exception:
                    pass

                try:
                    button.click(timeout=5000)
                    print("✓ FINAL PUBLISH CLICKED")
                    return True

                except Exception as e:
                    print(
                        f"Normal final click failed: {e}"
                    )

                    try:
                        button.click(
                            force=True,
                            timeout=5000
                        )

                        print(
                            "✓ FINAL PUBLISH FORCE CLICKED"
                        )

                        return True

                    except Exception as e2:
                        print(
                            f"❌ Final force click failed: "
                            f"{e2}"
                        )

        except Exception as e:
            print(
                f"⚠️ Final Publish search "
                f"{attempt + 1}: {e}"
            )

        page.wait_for_timeout(500)

    print("❌ FINAL Publish button not found.")

    return False


# ============================================================
# VERIFY PUBLICATION
# ============================================================

def verify_publication(page):

    print("\nVERIFYING PUBLISHED POST...")

    for attempt in range(30):

        try:

            current_url = page.url

            print(
                f"Current URL: {current_url}"
            )

            # REAL successful Serey URL
            if re.match(
                rf"^{re.escape(SEREY_URL)}/authors/[^/]+/[^/?#]+",
                current_url
            ):
                print("✓ POST URL FOUND!")
                print(f"Published URL: {current_url}")

                return True

        except Exception:
            pass

        page.wait_for_timeout(1000)

    print("❌ Publication could not be verified.")

    return False


# ============================================================
# DEBUG
# ============================================================

def save_debug(page):

    try:
        page.screenshot(
            path="serey_error.png",
            full_page=True
        )

        print(
            "Debug screenshot saved: "
            "serey_error.png"
        )

    except Exception as e:
        print(
            f"Could not save screenshot: {e}"
        )

    try:
        html = page.content()

        with open(
            "serey_error.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(html)

        print(
            "Debug HTML saved: "
            "serey_error.html"
        )

    except Exception as e:
        print(
            f"Could not save HTML: {e}"
        )


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish_post(page, post):

    title = post.get("title", "").strip()
    body = clean_body(post.get("body", ""))
    category = post.get("category", "blog")

    post_key = get_post_key(post)

    print("\n" + "=" * 60)
    print(f"Publishing: {title}")
    print(f"Post ID: {post_key}")
    print("=" * 60)

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image_url = extract_image_url(body)

    image_file = None

    if image_url:
        image_file = download_image(image_url)

    # --------------------------------------------------------
    # NEW POST PAGE
    # --------------------------------------------------------

    new_post_url = f"{SEREY_URL}/blog/post/new"

    print(f"New post URL: {new_post_url}")

    try:
        page.goto(
            new_post_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

    except Exception as e:
        print(f"❌ Could not open new post page: {e}")
        return False

    # --------------------------------------------------------
    # FIND INPUTS
    # --------------------------------------------------------

    try:

        inputs = page.locator("input")

        text_inputs = []

        for i in range(inputs.count()):

            try:
                inp = inputs.nth(i)

                if not inp.is_visible():
                    continue

                input_type = (
                    inp.get_attribute("type") or ""
                ).lower()

                if input_type in (
                    "text",
                    ""
                ):
                    text_inputs.append(inp)

            except Exception:
                continue

        if not text_inputs:
            print("❌ Title input not found.")
            save_debug(page)
            return False

        # First visible text input is title
        title_input = text_inputs[0]

        title_input.fill(title)

        print("✓ Title filled")

    except Exception as e:
        print(f"❌ Title fill error: {e}")
        save_debug(page)
        return False

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    body_filled = False

    try:

        textareas = page.locator("textarea")

        for i in range(textareas.count()):

            try:
                textarea = textareas.nth(i)

                if textarea.is_visible():

                    textarea.fill(body)

                    body_filled = True

                    print("✓ Body filled")
                    break

            except Exception:
                continue

    except Exception:
        pass

    # Try contenteditable if textarea not found
    if not body_filled:

        try:

            editable = page.locator(
                '[contenteditable="true"]'
            )

            for i in range(editable.count()):

                try:

                    element = editable.nth(i)

                    if element.is_visible():

                        element.fill(body)

                        body_filled = True

                        print(
                            "✓ Body filled "
                            "(contenteditable)"
                        )

                        break

                except Exception:
                    continue

        except Exception:
            pass

    if not body_filled:

        print("❌ Body editor not found.")
        save_debug(page)
        return False

    # --------------------------------------------------------
    # IMAGE UPLOAD
    # --------------------------------------------------------

    if image_file and os.path.exists(image_file):

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            if file_inputs.count() > 0:

                file_inputs.first.set_input_files(
                    image_file
                )

                print("✓ Thumbnail uploaded.")

                page.wait_for_timeout(1500)

                # IMPORTANT:
                # Only image crop modal is handled here.
                handle_image_crop_modal(page)

            else:
                print(
                    "⚠️ File input not found. "
                    "Continuing without image."
                )

        except Exception as e:
            print(
                f"⚠️ Thumbnail upload failed: {e}"
            )

    else:
        print("No thumbnail available.")

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    print("\nSearching for FIRST Publish...")

    first_publish_clicked = False

    for attempt in range(20):

        try:

            # If image crop modal exists, handle ONLY that modal.
            handle_image_crop_modal(page)

            buttons = get_visible_publish_buttons(page)

            print(
                f"Visible Publish buttons: "
                f"{len(buttons)}"
            )

            if buttons:

                button = buttons[-1]

                try:
                    button.scroll_into_view_if_needed()
                except Exception:
                    pass

                try:

                    button.click(timeout=5000)

                    print("✓ FIRST Publish CLICKED")

                    first_publish_clicked = True

                    break

                except Exception as e:

                    print(
                        f"Normal click failed: {e}"
                    )

                    try:

                        button.click(
                            force=True,
                            timeout=5000
                        )

                        print(
                            "✓ FIRST PUBLISH "
                            "FORCE CLICKED"
                        )

                        first_publish_clicked = True

                        break

                    except Exception as e2:

                        print(
                            f"Force click failed: {e2}"
                        )

        except Exception as e:

            print(
                f"Publish search "
                f"{attempt + 1}: {e}"
            )

        page.wait_for_timeout(500)

    if not first_publish_clicked:

        print("❌ FIRST Publish button not found.")
        save_debug(page)
        return False

    page.wait_for_timeout(2000)

    print(
        f"URL after first Publish: "
        f"{page.url}"
    )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    handle_category(page, category)

    # --------------------------------------------------------
    # CATEGORY CONFIRMATION
    #
    # IMPORTANT:
    # This Publish is NOT final publication.
    # It only confirms Serey's suggested category.
    # --------------------------------------------------------

    if not click_category_confirmation_publish(page):

        print("❌ Category confirmation failed.")
        save_debug(page)
        return False

    # --------------------------------------------------------
    # FINAL PUBLISH ON MAIN PAGE
    #
    # This was the missing step in the failed run.
    # --------------------------------------------------------

    if not click_final_publish(page):

        print("❌ FINAL Publish button not found.")
        save_debug(page)
        return False

    # --------------------------------------------------------
    # VERIFY REAL SEREY URL
    # --------------------------------------------------------

    success = verify_publication(page)

    if success:
        return True

    save_debug(page)

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    if not check_environment():
        return

    synced_posts = load_synced_posts()

    print(
        f"Already synced posts found: "
        f"{len(synced_posts)}"
    )

    # --------------------------------------------------------
    # GET ALL STEEM POSTS
    # --------------------------------------------------------

    posts = get_all_steem_posts()

    if not posts:

        print("❌ No Steem posts found.")
        return

    # --------------------------------------------------------
    # OLDEST 1000
    # --------------------------------------------------------

    selected_posts = posts[:OLDEST_POST_LIMIT]

    print(
        f"\nSelected oldest posts: "
        f"{len(selected_posts)}"
    )

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    skipped_count = 0
    unsynced_posts = []

    for post in selected_posts:

        post_key = get_post_key(post)

        # Permanent skip
        if post_key in PERMANENT_SKIP:

            skipped_count += 1
            continue

        # Already successfully synced
        if post_key in synced_posts:

            continue

        unsynced_posts.append(post)

    print(
        f"Permanent skipped posts found: "
        f"{skipped_count}"
    )

    print(
        f"Unsynced posts in oldest 1000: "
        f"{len(unsynced_posts)}"
    )

    if not unsynced_posts:

        print(
            "\n✓ All posts in the oldest 1000 "
            "queue are already processed."
        )

        return

    # --------------------------------------------------------
    # ONE POST PER RUN
    # --------------------------------------------------------

    posts_to_publish = unsynced_posts[:POSTS_PER_RUN]

    print(
        f"Publishing this run: "
        f"{len(posts_to_publish)}"
    )

    # --------------------------------------------------------
    # PLAYWRIGHT
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            if not login_serey(page):
                return

            # ------------------------------------------------
            # PUBLISH
            # ------------------------------------------------

            for post in posts_to_publish:

                post_key = get_post_key(post)

                success = False

                try:

                    success = publish_post(
                        page,
                        post
                    )

                except Exception as e:

                    print(
                        f"❌ Unexpected publishing error: "
                        f"{e}"
                    )

                    save_debug(page)

                    success = False

                if success:

                    # IMPORTANT:
                    # Save ONLY after real URL verification.
                    synced_posts.add(post_key)

                    save_synced_posts(
                        synced_posts
                    )

                    print(
                        f"✓ SUCCESS: {post_key}"
                    )

                else:

                    print(
                        f"❌ FAILED: {post_key}"
                    )

                    print(
                        "⚠️ This post was NOT added "
                        "to synced_posts.json."
                    )

        finally:

            context.close()
            browser.close()

    print("\n========================================")
    print("SYNC COMPLETED")
    print("========================================")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
