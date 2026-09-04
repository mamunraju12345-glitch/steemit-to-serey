import os
import json
import time
import re
import requests

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

STEEM_API = "https://api.steemit.com"
SEREY_URL = "https://bengali.serey.io"

STEEM_USERNAME = os.getenv("STEEM_USERNAME")
SEREY_USERNAME = os.getenv("SEREY_USERNAME")
SEREY_PASSWORD = os.getenv("SEREY_PASSWORD")

SYNC_FILE = "synced_posts.json"

OLDEST_POST_LIMIT = 1000
POSTS_PER_RUN = 1


# ============================================================
# PERMANENT SKIP LIST
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
# ENVIRONMENT
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
# SYNC FILE
# ============================================================

def load_synced_posts():

    if not os.path.exists(SYNC_FILE):
        return set()

    try:

        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return set(str(x) for x in data)

        return set()

    except Exception as e:

        print(
            f"⚠️ Could not read {SYNC_FILE}: {e}"
        )

        return set()


def save_synced_posts(posts):

    try:

        with open(
            SYNC_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                sorted(posts),
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            f"✓ Synced file updated: "
            f"{len(posts)} posts"
        )

    except Exception as e:

        print(
            f"❌ Failed saving synced posts: {e}"
        )


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
# GET ALL STEEM POSTS
# ============================================================

def get_all_steem_posts():

    print()
    print("=" * 60)
    print("COLLECTING STEEM POSTS")
    print("=" * 60)

    posts = []

    start_author = STEEM_USERNAME
    start_permlink = ""

    page_number = 0

    while True:

        page_number += 1

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

            print(
                f"❌ Steem API error "
                f"page {page_number}: {e}"
            )

            break

        if not result:
            break

        print(
            f"Steem page {page_number}: "
            f"{len(result)} posts"
        )

        for post in result:

            author = post.get(
                "author",
                ""
            )

            permlink = post.get(
                "permlink",
                ""
            )

            # Only own posts
            if author != STEEM_USERNAME:
                continue

            # Only root posts
            if post.get("parent_author"):
                continue

            # Ignore empty/deleted posts
            if not post.get("title"):
                continue

            posts.append(post)

        if len(result) < 100:
            break

        last_post = result[-1]

        start_author = last_post.get(
            "author"
        )

        start_permlink = last_post.get(
            "permlink"
        )

        if not start_author or not start_permlink:
            break

        time.sleep(0.2)

    print()
    print(f"Total posts: {len(posts)}")

    # API gives newest first.
    # Reverse = oldest first.
    posts.reverse()

    return posts


# ============================================================
# POST KEY
# ============================================================

def get_post_key(post):

    return (
        f"{post.get('author', '')}/"
        f"{post.get('permlink', '')}"
    )


# ============================================================
# CLEAN BODY
# ============================================================

def clean_body(body):

    if not body:
        return ""

    body = re.sub(
        r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>",
        "",
        body,
        flags=re.IGNORECASE
    )

    return body.strip()


# ============================================================
# IMAGE URL
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

        match = re.search(
            pattern,
            body,
            re.IGNORECASE
        )

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

    print(
        f"Downloading image: {image_url}"
    )

    try:

        headers = {
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120 Safari/537.36"
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
                "⚠️ URL did not return an image."
            )

            return None

        extension = ".jpg"

        if "png" in content_type:
            extension = ".png"

        elif "webp" in content_type:
            extension = ".webp"

        elif "gif" in content_type:
            extension = ".gif"

        filename = (
            f"steem_thumbnail{extension}"
        )

        with open(
            filename,
            "wb"
        ) as f:

            f.write(response.content)

        print(
            f"✓ Image downloaded: {filename}"
        )

        return filename

    except Exception as e:

        print(
            f"Image attempt failed: {e}"
        )

        print(
            "⚠️ Image unavailable. "
            "Continuing without image."
        )

        return None


# ============================================================
# LOGIN
# ============================================================

def login_serey(page):

    print()
    print("Logging into Serey...")

    try:

        page.goto(
            f"{SEREY_URL}/login",
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

    except Exception as e:

        print(
            f"❌ Could not open login page: {e}"
        )

        return False

    inputs = page.locator("input")

    if inputs.count() < 2:

        print(
            "❌ Login inputs not found."
        )

        return False

    try:

        inputs.nth(0).fill(
            SEREY_USERNAME
        )

        inputs.nth(1).fill(
            SEREY_PASSWORD
        )

    except Exception as e:

        print(
            f"❌ Could not fill login form: {e}"
        )

        return False

    buttons = page.locator("button")

    login_clicked = False

    for i in range(buttons.count()):

        try:

            button = buttons.nth(i)

            if not button.is_visible():
                continue

            text = (
                button.inner_text()
                .strip()
                .lower()
            )

            if (
                "login" in text
                or "sign in" in text
            ):

                button.click()

                login_clicked = True

                break

        except Exception:
            continue

    if not login_clicked:

        print(
            "❌ Login button not found."
        )

        return False

    page.wait_for_timeout(5000)

    if "/login" not in page.url.lower():

        print(
            "✓ SEREY LOGIN VERIFIED!"
        )

        return True

    try:

        body_text = (
            page.locator("body")
            .inner_text()
            .lower()
        )

        if (
            "logout" in body_text
            or SEREY_USERNAME.lower()
            in body_text
        ):

            print(
                "✓ SEREY LOGIN VERIFIED!"
            )

            return True

    except Exception:
        pass

    print(
        "❌ SEREY LOGIN FAILED."
    )

    return False


# ============================================================
# VISIBLE PUBLISH BUTTONS
# ============================================================

def get_visible_publish_buttons(page):

    result = []

    buttons = page.locator("button")

    for i in range(buttons.count()):

        try:

            button = buttons.nth(i)

            if not button.is_visible():
                continue

            text = (
                button.inner_text()
                .strip()
                .lower()
            )

            if text == "publish":
                result.append(button)

        except Exception:
            continue

    return result


# ============================================================
# IMAGE CROP MODAL
# ============================================================

def handle_image_crop_modal(page):

    try:

        # IMPORTANT:
        # Only image crop modal.
        # Do NOT touch normal Serey category modal.
        modal = page.locator(
            ".antd-img-crop-modal:visible"
        )

        if modal.count() == 0:
            return True

        print(
            "Image crop modal detected."
        )

        buttons = modal.locator("button")

        for i in range(buttons.count()):

            try:

                button = buttons.nth(i)

                if not button.is_visible():
                    continue

                text = (
                    button.inner_text()
                    .strip()
                    .lower()
                )

                if text in (
                    "ok",
                    "crop",
                    "confirm",
                    "done"
                ):

                    button.click()

                    page.wait_for_timeout(1000)

                    print(
                        "✓ Image crop confirmed."
                    )

                    return True

            except Exception:
                continue

        print(
            "⚠️ Could not identify "
            "image crop confirmation."
        )

    except Exception as e:

        print(
            f"⚠️ Image crop handling error: {e}"
        )

    return True


# ============================================================
# CATEGORY
# ============================================================

def handle_category(page, category):

    print(
        f"Steemit category: {category}"
    )

    print(
        "No category selector. Continuing."
    )


# ============================================================
# CATEGORY CONFIRMATION MODAL
# ============================================================

def click_category_confirmation_publish(page):

    print(
        "Searching for Serey Publish confirmation..."
    )

    for attempt in range(30):

        try:

            modal_locator = page.locator(
                ".ant-modal-wrap:visible"
            )

            if modal_locator.count() > 0:

                modal = modal_locator.last

                try:

                    modal_text = (
                        modal.inner_text()
                        .strip()
                    )

                    print(
                        "Serey modal detected:"
                    )

                    print(modal_text)

                except Exception:
                    pass

                buttons = modal.locator(
                    "button"
                )

                publish_buttons = []

                for i in range(
                    buttons.count()
                ):

                    try:

                        button = buttons.nth(i)

                        if not button.is_visible():
                            continue

                        text = (
                            button.inner_text()
                            .strip()
                            .lower()
                        )

                        if text == "publish":

                            publish_buttons.append(
                                button
                            )

                    except Exception:
                        continue

                if publish_buttons:

                    print(
                        "✓ Publish button found "
                        "inside Serey modal: "
                        f"{len(publish_buttons)}"
                    )

                    publish_buttons[-1].click(
                        force=True
                    )

                    page.wait_for_timeout(
                        1000
                    )

                    # Wait until category modal
                    # actually disappears.
                    for _ in range(30):

                        try:

                            if page.locator(
                                ".ant-modal-wrap:visible"
                            ).count() == 0:

                                print(
                                    "✓ Category "
                                    "confirmation modal "
                                    "closed."
                                )

                                return True

                        except Exception:
                            pass

                        page.wait_for_timeout(
                            300
                        )

                    print(
                        "⚠️ Category modal did "
                        "not close."
                    )

                    return False

        except Exception as e:

            print(
                f"Category modal check "
                f"{attempt + 1}: {e}"
            )

        page.wait_for_timeout(500)

    # No modal can mean Serey did not ask
    # for category confirmation.
    print(
        "No Serey confirmation modal found."
    )

    return True


# ============================================================
# FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    print()
    print(
        "Searching for FINAL Publish..."
    )

    # IMPORTANT:
    # Never click a Publish while a normal
    # Ant Design modal is visible.
    for _ in range(20):

        try:

            if page.locator(
                ".ant-modal-wrap:visible"
            ).count() == 0:

                break

        except Exception:
            pass

        page.wait_for_timeout(500)

    # Extra wait after category modal.
    page.wait_for_timeout(1500)

    for attempt in range(30):

        try:

            # If modal exists, wait.
            if page.locator(
                ".ant-modal-wrap:visible"
            ).count() > 0:

                page.wait_for_timeout(500)

                continue

            publish_buttons = (
                get_visible_publish_buttons(page)
            )

            print(
                f"Visible Publish buttons: "
                f"{len(publish_buttons)}"
            )

            if publish_buttons:

                # Main page final Publish.
                button = publish_buttons[-1]

                try:

                    button.scroll_into_view_if_needed()

                except Exception:
                    pass

                try:

                    button.click(
                        timeout=5000
                    )

                    print(
                        "✓ FINAL PUBLISH CLICKED"
                    )

                    return True

                except Exception as e:

                    print(
                        f"Normal final click "
                        f"failed: {e}"
                    )

                    try:

                        button.click(
                            force=True,
                            timeout=5000
                        )

                        print(
                            "✓ FINAL PUBLISH "
                            "FORCE CLICKED"
                        )

                        return True

                    except Exception as e2:

                        print(
                            f"Final force click "
                            f"failed: {e2}"
                        )

        except Exception as e:

            print(
                f"Final Publish search "
                f"{attempt + 1}: {e}"
            )

        page.wait_for_timeout(700)

    print(
        "❌ FINAL Publish button not found."
    )

    return False


# ============================================================
# VERIFY
# ============================================================

def verify_publication(page):

    print()
    print(
        "VERIFYING PUBLISHED POST..."
    )

    for attempt in range(40):

        try:

            current_url = page.url

            print(
                f"Current URL: {current_url}"
            )

            # Must be real author/post URL.
            if re.match(
                rf"^{re.escape(SEREY_URL)}/authors/[^/]+/[^/?#]+",
                current_url
            ):

                print(
                    "✓ POST URL FOUND!"
                )

                print(
                    f"Published URL: "
                    f"{current_url}"
                )

                return True

        except Exception:
            pass

        page.wait_for_timeout(
            1000
        )

    print(
        "❌ Publication could not be verified."
    )

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

    title = (
        post.get("title", "")
        .strip()
    )

    body = clean_body(
        post.get("body", "")
    )

    category = (
        post.get(
            "category",
            "blog"
        )
    )

    post_key = get_post_key(post)

    print()
    print("=" * 60)
    print(
        f"Publishing: {title}"
    )
    print(
        f"Post ID: {post_key}"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image_url = extract_image_url(body)

    image_file = None

    if image_url:

        image_file = download_image(
            image_url
        )

    # --------------------------------------------------------
    # NEW POST
    # --------------------------------------------------------

    new_post_url = (
        f"{SEREY_URL}/blog/post/new"
    )

    print(
        f"New post URL: {new_post_url}"
    )

    try:

        page.goto(
            new_post_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(
            3000
        )

    except Exception as e:

        print(
            f"❌ Could not open new post page: {e}"
        )

        return False

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    try:

        inputs = page.locator(
            "input"
        )

        text_inputs = []

        for i in range(
            inputs.count()
        ):

            try:

                inp = inputs.nth(i)

                if not inp.is_visible():
                    continue

                input_type = (
                    inp.get_attribute(
                        "type"
                    )
                    or ""
                ).lower()

                if input_type in (
                    "",
                    "text"
                ):

                    text_inputs.append(
                        inp
                    )

            except Exception:
                continue

        if not text_inputs:

            print(
                "❌ Title input not found."
            )

            save_debug(page)

            return False

        text_inputs[0].fill(
            title
        )

        print(
            "✓ Title filled"
        )

    except Exception as e:

        print(
            f"❌ Title fill error: {e}"
        )

        save_debug(page)

        return False

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    body_filled = False

    try:

        textareas = page.locator(
            "textarea"
        )

        for i in range(
            textareas.count()
        ):

            try:

                textarea = textareas.nth(i)

                if textarea.is_visible():

                    textarea.fill(
                        body
                    )

                    body_filled = True

                    print(
                        "✓ Body filled"
                    )

                    break

            except Exception:
                continue

    except Exception:
        pass

    # Contenteditable fallback
    if not body_filled:

        try:

            editors = page.locator(
                '[contenteditable="true"]'
            )

            for i in range(
                editors.count()
            ):

                try:

                    editor = editors.nth(i)

                    if editor.is_visible():

                        editor.fill(
                            body
                        )

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

        print(
            "❌ Body editor not found."
        )

        save_debug(page)

        return False

    # --------------------------------------------------------
    # IMAGE UPLOAD
    # --------------------------------------------------------

    if (
        image_file
        and os.path.exists(image_file)
    ):

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            if file_inputs.count() > 0:

                file_inputs.first.set_input_files(
                    image_file
                )

                print(
                    "✓ Thumbnail uploaded."
                )

                page.wait_for_timeout(
                    1500
                )

                handle_image_crop_modal(
                    page
                )

            else:

                print(
                    "⚠️ File input not found."
                )

        except Exception as e:

            print(
                f"⚠️ Thumbnail upload failed: {e}"
            )

    else:

        print(
            "No thumbnail available."
        )

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    print()
    print(
        "Searching for FIRST Publish..."
    )

    first_clicked = False

    for attempt in range(30):

        try:

            handle_image_crop_modal(
                page
            )

            buttons = (
                get_visible_publish_buttons(
                    page
                )
            )

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

                    button.click(
                        timeout=5000
                    )

                    print(
                        "✓ FIRST Publish CLICKED"
                    )

                    first_clicked = True

                    break

                except Exception as e:

                    print(
                        f"Normal click failed: "
                        f"{e}"
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

                        first_clicked = True

                        break

                    except Exception as e2:

                        print(
                            f"Force click failed: "
                            f"{e2}"
                        )

        except Exception as e:

            print(
                f"Publish search "
                f"{attempt + 1}: {e}"
            )

        page.wait_for_timeout(
            500
        )

    if not first_clicked:

        print(
            "❌ FIRST Publish button not found."
        )

        save_debug(page)

        return False

    page.wait_for_timeout(
        2000
    )

    print(
        f"URL after first Publish: "
        f"{page.url}"
    )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    handle_category(
        page,
        category
    )

    # --------------------------------------------------------
    # CATEGORY MODAL
    # --------------------------------------------------------

    category_ok = (
        click_category_confirmation_publish(
            page
        )
    )

    if not category_ok:

        print(
            "❌ Category confirmation failed."
        )

        save_debug(page)

        return False

    # --------------------------------------------------------
    # VERY IMPORTANT:
    # FINAL PUBLISH
    # --------------------------------------------------------

    print()
    print(
        "Category confirmed."
    )

    print(
        "Now looking for MAIN PAGE FINAL Publish..."
    )

    final_ok = (
        click_final_publish(
            page
        )
    )

    if not final_ok:

        print(
            "❌ FINAL Publish button not found."
        )

        save_debug(page)

        return False

    # --------------------------------------------------------
    # VERIFY REAL URL
    # --------------------------------------------------------

    success = verify_publication(
        page
    )

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

    synced_posts = (
        load_synced_posts()
    )

    print(
        f"Already synced posts found: "
        f"{len(synced_posts)}"
    )

    # --------------------------------------------------------
    # COLLECT POSTS
    # --------------------------------------------------------

    posts = (
        get_all_steem_posts()
    )

    if not posts:

        print(
            "❌ No Steem posts found."
        )

        return

    # --------------------------------------------------------
    # OLDEST 1000 ONLY
    # --------------------------------------------------------

    selected_posts = (
        posts[:OLDEST_POST_LIMIT]
    )

    print(
        f"Selected oldest posts: "
        f"{len(selected_posts)}"
    )

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    unsynced_posts = []

    skipped_count = 0

    for post in selected_posts:

        key = get_post_key(post)

        if key in PERMANENT_SKIP:

            skipped_count += 1

            continue

        if key in synced_posts:

            continue

        unsynced_posts.append(
            post
        )

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
            "✓ No unsynced posts remain "
            "in oldest 1000."
        )

        return

    # --------------------------------------------------------
    # ONE POST
    # --------------------------------------------------------

    posts_to_publish = (
        unsynced_posts[
            :POSTS_PER_RUN
        ]
    )

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
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            # LOGIN
            if not login_serey(page):
                return

            # PUBLISH ONE
            for post in posts_to_publish:

                key = get_post_key(
                    post
                )

                try:

                    success = publish_post(
                        page,
                        post
                    )

                except Exception as e:

                    print(
                        f"❌ Unexpected error: "
                        f"{e}"
                    )

                    save_debug(page)

                    success = False

                # ------------------------------------------------
                # ONLY SUCCESSFUL REAL PUBLICATION IS SAVED
                # ------------------------------------------------

                if success:

                    synced_posts.add(
                        key
                    )

                    save_synced_posts(
                        synced_posts
                    )

                    print()
                    print(
                        f"✓ SUCCESS: {key}"
                    )

                else:

                    print()
                    print(
                        f"❌ FAILED: {key}"
                    )

                    print(
                        "⚠️ This post was NOT "
                        "added to synced_posts.json."
                    )

        finally:

            context.close()

            browser.close()

    print()
    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
