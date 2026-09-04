import os
import re
import json
import time
import html
import requests

from urllib.parse import urljoin

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# CONFIG
# ============================================================

STEEM_USERNAME = os.getenv("STEEM_USERNAME", "").strip()

SEREY_USERNAME = os.getenv("SEREY_USERNAME", "").strip()
SEREY_PASSWORD = os.getenv("SEREY_PASSWORD", "").strip()

SEREY_URL = "https://bengali.serey.io"
NEW_POST_URL = f"{SEREY_URL}/blog/post/new"

SYNC_FILE = "synced_posts.json"

POSTS_PER_RUN = 1

STEEM_API = "https://api.steemit.com"


# ============================================================
# THESE 11 POSTS ARE PERMANENTLY SKIPPED
# ============================================================

PERMANENTLY_SKIPPED = {
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
# LOG
# ============================================================

def log(message):
    print(message, flush=True)


# ============================================================
# NORMALIZE POST ID
# ============================================================

def normalize_post_id(author, permlink=None):

    if permlink is None:

        value = str(author or "").strip()

        value = value.replace(
            "https://steemit.com/",
            ""
        )

        value = value.replace(
            "https://steemit.com",
            ""
        )

        value = value.lstrip("/")

        if value.startswith("@"):
            value = value[1:]

        # Convert / to /
        parts = value.split("/")

        if len(parts) >= 2:

            username = parts[-2].lstrip("@")
            post_name = parts[-1]

            return f"{username}/{post_name}"

        return value

    author = str(author or "").strip()
    permlink = str(permlink or "").strip()

    author = author.lstrip("@")

    if not author or not permlink:
        return ""

    return f"{author}/{permlink}"


# ============================================================
# LOAD SYNCED POSTS
# ============================================================

def load_synced():

    synced = set()

    if not os.path.exists(SYNC_FILE):

        log(
            "synced_posts.json not found. "
            "Starting with empty synced list."
        )

        return synced

    try:

        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):

            for item in data:

                normalized = normalize_post_id(
                    item
                )

                if normalized:
                    synced.add(normalized)

        log(
            f"Previously synced: {len(synced)}"
        )

    except Exception as e:

        log(
            f"Could not read synced_posts.json: {e}"
        )

    return synced


# ============================================================
# SAVE SYNCED POSTS
# ============================================================

def save_synced(synced):

    try:

        data = sorted(
            list(synced)
        )

        with open(
            SYNC_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        log(
            f"✓ synced_posts.json updated: "
            f"{len(data)} posts"
        )

        return True

    except Exception as e:

        log(
            f"❌ Could not save synced_posts.json: {e}"
        )

        return False


# ============================================================
# STEEM RPC
# ============================================================

def steem_rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:

        response = requests.post(
            STEEM_API,
            json=payload,
            timeout=40
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:

            log(
                f"Steem RPC error: {data['error']}"
            )

            return None

        return data.get("result")

    except Exception as e:

        log(
            f"Steem RPC request failed: {e}"
        )

        return None


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_steem_posts():

    log(
        f"Getting posts from @{STEEM_USERNAME}..."
    )

    all_posts = []

    start_author = STEEM_USERNAME
    start_permlink = ""

    page_number = 0

    while True:

        page_number += 1

        result = steem_rpc(
            "condenser_api.get_discussions_by_blog",
            [{
                "tag": STEEM_USERNAME,
                "start_author": start_author,
                "start_permlink": start_permlink,
                "limit": 100,
            }]
        )

        if not result:
            break

        log(
            f"Steem page {page_number}: "
            f"{len(result)} posts"
        )

        all_posts.extend(result)

        if len(result) < 100:
            break

        last_post = result[-1]

        last_author = last_post.get(
            "author",
            ""
        )

        last_permlink = last_post.get(
            "permlink",
            ""
        )

        if not last_author or not last_permlink:
            break

        # Prevent infinite loop
        if (
            last_author == start_author
            and last_permlink == start_permlink
        ):
            break

        start_author = last_author
        start_permlink = last_permlink

        if page_number >= 100:
            break

        time.sleep(0.3)

    # --------------------------------------------------------
    # Remove duplicate posts
    # --------------------------------------------------------

    unique_posts = {}

    for post in all_posts:

        author = post.get(
            "author",
            ""
        )

        permlink = post.get(
            "permlink",
            ""
        )

        post_id = normalize_post_id(
            author,
            permlink
        )

        if post_id:

            unique_posts[post_id] = post

    posts = list(
        unique_posts.values()
    )

    log(
        f"Total posts: {len(posts)}"
    )

    return posts


# ============================================================
# CLEAN BODY
# ============================================================

def clean_body(body):

    if not body:
        return ""

    body = html.unescape(body)

    # Remove HTML image tags
    body = re.sub(
        r"<img[^>]*>",
        "",
        body,
        flags=re.I
    )

    # Remove Steem esteem images
    body = re.sub(
        r"!\[[^\]]*\]\("
        r"https?://img\.esteem\.ws/[^)]+"
        r"\)",
        "",
        body,
        flags=re.I
    )

    # Remove excessive blank lines
    body = re.sub(
        r"\n{4,}",
        "\n\n\n",
        body
    )

    return body.strip()


# ============================================================
# FIND IMAGE
# ============================================================

def get_image_url(body):

    if not body:
        return None

    patterns = [

        r"!\[[^\]]*\]\((https?://[^)\s]+)\)",

        r'<img[^>]+src=["\']([^"\']+)["\']',

        r"(https?://img\.esteem\.ws/[^\s)\"']+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            body,
            flags=re.I
        )

        if match:

            return match.group(1)

    return None


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(image_url):

    if not image_url:

        log(
            "No thumbnail available."
        )

        return None

    log(
        f"Downloading image: {image_url}"
    )

    candidates = [
        image_url
    ]

    # Fallback for esteem.ws
    if "img.esteem.ws/" in image_url:

        filename = (
            image_url
            .rstrip("/")
            .split("/")[-1]
        )

        candidates.append(
            f"https://steemitimages.com/{filename}"
        )

    for url in candidates:

        try:

            log(
                f"Trying image: {url}"
            )

            response = requests.get(
                url,
                timeout=25,
                headers={
                    "User-Agent":
                    "Mozilla/5.0"
                }
            )

            content_type = (
                response.headers
                .get(
                    "content-type",
                    ""
                )
                .lower()
            )

            if response.status_code != 200:

                log(
                    f"Image HTTP "
                    f"{response.status_code}"
                )

                continue

            if not content_type.startswith(
                "image/"
            ):

                log(
                    f"Not an image: "
                    f"{content_type}"
                )

                continue

            with open(
                "article_image.jpg",
                "wb"
            ) as f:

                f.write(
                    response.content
                )

            log(
                "✓ Image downloaded"
            )

            return "article_image.jpg"

        except Exception as e:

            log(
                f"Image attempt failed: {e}"
            )

    log(
        "⚠️ Image unavailable. "
        "Continuing WITHOUT image."
    )

    return None


# ============================================================
# PAGE TEXT
# ============================================================

def get_page_text(page):

    try:

        return page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

    except Exception:

        return ""


# ============================================================
# FIND FORM ERRORS
# ============================================================

def find_form_errors(page):

    errors = []

    selectors = [
        ".error",
        ".errors",
        "[role='alert']",
        ".invalid-feedback",
        ".text-danger",
        ".alert-danger",
        ".alert-error",
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            for i in range(count):

                try:

                    element = locator.nth(i)

                    if not element.is_visible():
                        continue

                    text = element.inner_text().strip()

                    if text:
                        errors.append(text)

                except Exception:
                    continue

        except Exception:
            continue

    # Remove duplicates
    return list(
        dict.fromkeys(errors)
    )


# ============================================================
# SAVE DEBUG FILES
# ============================================================

def save_debug(page):

    try:

        page.screenshot(
            path="serey_error.png",
            full_page=True
        )

        log(
            "Debug screenshot saved: "
            "serey_error.png"
        )

    except Exception as e:

        log(
            f"Screenshot failed: {e}"
        )

    try:

        page_content = page.content()

        with open(
            "serey_error.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(page_content)

        log(
            "Debug HTML saved: "
            "serey_error.html"
        )

    except Exception as e:

        log(
            f"HTML save failed: {e}"
        )


# ============================================================
# FIND PUBLISH BUTTONS
# ============================================================

def find_publish_buttons(page):

    result = []

    try:

        locator = page.locator(
            "button, input[type='submit'], "
            "input[type='button'], a"
        )

        count = locator.count()

        for i in range(count):

            try:

                element = locator.nth(i)

                if not element.is_visible():
                    continue

                text = ""

                try:

                    text = (
                        element
                        .inner_text()
                        .strip()
                    )

                except Exception:
                    pass

                if not text:

                    try:

                        text = (
                            element
                            .get_attribute("value")
                            or ""
                        ).strip()

                    except Exception:
                        text = ""

                if text.lower() == "publish":

                    result.append(
                        element
                    )

            except Exception:
                continue

    except Exception:
        pass

    return result


# ============================================================
# CLICK PUBLISH
# ============================================================

def click_publish(page, stage):

    log(
        f"Searching for {stage} Publish..."
    )

    buttons = find_publish_buttons(
        page
    )

    log(
        f"Visible Publish buttons: "
        f"{len(buttons)}"
    )

    if not buttons:

        log(
            f"❌ {stage} Publish button not found."
        )

        return False

    button = buttons[-1]

    try:

        if button.is_disabled():

            log(
                f"❌ {stage} Publish button "
                f"is DISABLED."
            )

            return False

    except Exception:
        pass

    try:

        button.scroll_into_view_if_needed()

    except Exception:
        pass

    time.sleep(1)

    try:

        button.click(
            timeout=15000
        )

        log(
            f"✓ {stage.upper()} PUBLISH CLICKED"
        )

        return True

    except Exception as e:

        log(
            f"Normal click failed: {e}"
        )

        try:

            button.click(
                force=True,
                timeout=15000
            )

            log(
                f"✓ {stage.upper()} "
                f"PUBLISH FORCE CLICKED"
            )

            return True

        except Exception as e2:

            log(
                f"❌ Publish click failed: {e2}"
            )

            return False


# ============================================================
# CATEGORY
# ============================================================

def handle_category(page, category):

    if not category:
        return

    log(
        f"Steemit category: {category}"
    )

    selectors = [

        "select[name*='category' i]",

        "select[id*='category' i]",

        "input[name*='category' i]",

        "input[placeholder*='category' i]",

        "[role='combobox']",
    ]

    handled = False

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            if count == 0:
                continue

            for i in range(count):

                element = locator.nth(i)

                if not element.is_visible():
                    continue

                tag = element.evaluate(
                    "(e) => e.tagName"
                )

                if tag == "SELECT":

                    try:

                        element.select_option(
                            label=category
                        )

                        handled = True

                    except Exception:

                        try:

                            element.select_option(
                                value=category
                            )

                            handled = True

                        except Exception:
                            pass

                else:

                    try:

                        element.fill(
                            category
                        )

                        time.sleep(1)

                        page.keyboard.press(
                            "ArrowDown"
                        )

                        page.keyboard.press(
                            "Enter"
                        )

                        handled = True

                    except Exception:
                        pass

                if handled:
                    break

            if handled:
                break

        except Exception:
            continue

    if handled:

        log(
            "✓ Category handled."
        )

    else:

        log(
            "No category selector. "
            "Continuing."
        )


# ============================================================
# VERIFY PUBLISHED URL
# ============================================================

def verify_publication(page):

    log(
        "VERIFYING PUBLISHED POST..."
    )

    for attempt in range(20):

        time.sleep(2)

        current_url = page.url

        log(
            f"Current URL: {current_url}"
        )

        # ====================================================
        # SUCCESS
        # ====================================================

        if "/authors/" in current_url:

            log(
                "✓ POST URL FOUND!"
            )

            return True, current_url

        # ====================================================
        # CHECK LINKS
        # ====================================================

        try:

            links = page.locator(
                "a[href*='/authors/']"
            )

            count = links.count()

            for i in range(count):

                try:

                    href = links.nth(i).get_attribute(
                        "href"
                    )

                    if href and "/authors/" in href:

                        final_url = urljoin(
                            SEREY_URL,
                            href
                        )

                        log(
                            f"✓ POST URL FOUND: "
                            f"{final_url}"
                        )

                        return True, final_url

                except Exception:
                    continue

        except Exception:
            pass

        # ====================================================
        # CHECK FORM ERRORS
        # ====================================================

        errors = find_form_errors(
            page
        )

        if errors:

            log(
                "⚠️ Serey form error: "
                + " | ".join(errors[:5])
            )

    log(
        "❌ Publication could not be verified."
    )

    save_debug(page)

    return False, None


# ============================================================
# LOGIN
# ============================================================

def login_serey(page):

    log(
        "Logging into Serey..."
    )

    # --------------------------------------------------------
    # Open new post page
    # --------------------------------------------------------

    try:

        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

    except Exception as e:

        log(
            f"Could not open Serey: {e}"
        )

    time.sleep(3)

    # --------------------------------------------------------
    # Check if already logged in
    # --------------------------------------------------------

    try:

        password_fields = page.locator(
            "input[type='password']"
        )

        if password_fields.count() == 0:

            log(
                "✓ SEREY LOGIN VERIFIED!"
            )

            return True

    except Exception:
        pass

    # --------------------------------------------------------
    # Find login link/button
    # --------------------------------------------------------

    selectors = [

        "a[href*='login']",

        "button:has-text('Login')",

        "button:has-text('Log in')",

        "text=Login",

        "text=Log in",

        "text=Sign In",
    ]

    clicked = False

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            for i in range(count):

                element = locator.nth(i)

                if not element.is_visible():
                    continue

                element.click(
                    timeout=10000
                )

                clicked = True

                break

            if clicked:
                break

        except Exception:
            continue

    time.sleep(3)

    # --------------------------------------------------------
    # Find login fields
    # --------------------------------------------------------

    username_field = None
    password_field = None

    username_selectors = [

        "input[name='username']",

        "input[name='email']",

        "input[type='email']",

        "input[placeholder*='username' i]",

        "input[placeholder*='email' i]",
    ]

    for selector in username_selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                element = locator.nth(i)

                if element.is_visible():

                    username_field = element

                    break

            if username_field:
                break

        except Exception:
            continue

    password_locator = page.locator(
        "input[type='password']"
    )

    for i in range(
        password_locator.count()
    ):

        try:

            element = password_locator.nth(i)

            if element.is_visible():

                password_field = element

                break

        except Exception:
            continue

    # --------------------------------------------------------
    # Fill login
    # --------------------------------------------------------

    if username_field and password_field:

        log(
            "Filling Serey login..."
        )

        username_field.fill(
            SEREY_USERNAME
        )

        password_field.fill(
            SEREY_PASSWORD
        )

        submitted = False

        submit_selectors = [

            "button[type='submit']",

            "input[type='submit']",

            "button:has-text('Login')",

            "button:has-text('Log in')",
        ]

        for selector in submit_selectors:

            try:

                locator = page.locator(
                    selector
                )

                for i in range(
                    locator.count()
                ):

                    element = locator.nth(i)

                    if element.is_visible():

                        element.click(
                            timeout=10000
                        )

                        submitted = True

                        break

                if submitted:
                    break

            except Exception:
                continue

        time.sleep(5)

    # --------------------------------------------------------
    # Open post page again
    # --------------------------------------------------------

    try:

        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

    except Exception:
        pass

    time.sleep(4)

    # --------------------------------------------------------
    # Verify login
    # --------------------------------------------------------

    try:

        password_count = page.locator(
            "input[type='password']"
        ).count()

        if password_count == 0:

            log(
                f"After login URL: {page.url}"
            )

            log(
                "✓ SEREY LOGIN VERIFIED"
            )

            return True

    except Exception:
        pass

    log(
        "❌ SEREY LOGIN FAILED"
    )

    save_debug(page)

    return False


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish_post(page, post):

    author = post.get(
        "author",
        ""
    )

    permlink = post.get(
        "permlink",
        ""
    )

    title = post.get(
        "title",
        ""
    )

    body = post.get(
        "body",
        ""
    )

    category = post.get(
        "category",
        ""
    )

    post_id = normalize_post_id(
        author,
        permlink
    )

    log("")
    log(
        "========================================"
    )
    log(
        f"Publishing: {title}"
    )
    log(
        f"Post ID: {post_id}"
    )
    log(
        "========================================"
    )

    # ========================================================
    # SAFETY: NEVER PUBLISH THE 11 OLD POSTS
    # ========================================================

    if post_id in PERMANENTLY_SKIPPED:

        log(
            "⏭️ This post is in the permanent "
            "skip list."
        )

        return False

    # ========================================================
    # BODY
    # ========================================================

    clean_content = clean_body(
        body
    )

    image_url = get_image_url(
        body
    )

    image_file = download_image(
        image_url
    )

    # ========================================================
    # OPEN NEW POST
    # ========================================================

    try:

        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

    except Exception as e:

        log(
            f"❌ New post page failed: {e}"
        )

        save_debug(page)

        return False

    time.sleep(3)

    log(
        f"New post URL: {page.url}"
    )

    # ========================================================
    # TITLE
    # ========================================================

    title_selectors = [

        "input[name='title']",

        "textarea[name='title']",

        "input[placeholder*='title' i]",
    ]

    title_field = None

    for selector in title_selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                element = locator.nth(i)

                if element.is_visible():

                    title_field = element

                    break

            if title_field:
                break

        except Exception:
            continue

    if not title_field:

        log(
            "❌ Title field not found."
        )

        save_debug(page)

        return False

    try:

        title_field.fill(
            title
        )

        log(
            "✓ Title filled"
        )

    except Exception as e:

        log(
            f"❌ Title fill failed: {e}"
        )

        save_debug(page)

        return False

    # ========================================================
    # BODY
    # ========================================================

    body_selectors = [

        "textarea[name='body']",

        "textarea[name='content']",

        "textarea[placeholder*='body' i]",

        "textarea[placeholder*='content' i]",

        "[contenteditable='true']",
    ]

    body_field = None

    for selector in body_selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                element = locator.nth(i)

                if element.is_visible():

                    body_field = element

                    break

            if body_field:
                break

        except Exception:
            continue

    if not body_field:

        log(
            "❌ Body field not found."
        )

        save_debug(page)

        return False

    try:

        body_field.fill(
            clean_content
        )

        log(
            "✓ Body filled"
        )

    except Exception as e:

        log(
            f"❌ Body fill failed: {e}"
        )

        save_debug(page)

        return False

    # ========================================================
    # IMAGE
    # ========================================================

    if image_file:

        try:

            inputs = page.locator(
                "input[type='file']"
            )

            uploaded = False

            for i in range(
                inputs.count()
            ):

                try:

                    inputs.nth(i).set_input_files(
                        image_file
                    )

                    uploaded = True

                    break

                except Exception:
                    continue

            if uploaded:

                log(
                    "✓ Thumbnail uploaded."
                )

            else:

                log(
                    "⚠️ Thumbnail upload skipped."
                )

        except Exception as e:

            log(
                f"Thumbnail upload failed: {e}"
            )

    else:

        log(
            "✓ Continuing without thumbnail."
        )

    # ========================================================
    # FIRST PUBLISH
    # ========================================================

    time.sleep(2)

    if not click_publish(
        page,
        "FIRST"
    ):

        save_debug(page)

        return False

    log(
        f"URL after first Publish: "
        f"{page.url}"
    )

    time.sleep(4)

    # ========================================================
    # CATEGORY
    # ========================================================

    handle_category(
        page,
        category
    )

    time.sleep(2)

    # ========================================================
    # FINAL PUBLISH
    # ========================================================

    if not click_publish(
        page,
        "FINAL"
    ):

        save_debug(page)

        return False

    # ========================================================
    # VERIFY REAL PUBLISHED URL
    # ========================================================

    success, published_url = verify_publication(
        page
    )

    if not success:

        log(
            "⚠️ NOT SAVED AS SYNCED."
        )

        return False

    log(
        f"✓ PUBLISHED SUCCESSFULLY:"
    )

    log(
        published_url
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # ENV CHECK
    # --------------------------------------------------------

    if not STEEM_USERNAME:

        log(
            "❌ STEEM_USERNAME is missing."
        )

        return

    if not SEREY_USERNAME:

        log(
            "❌ SEREY_USERNAME is missing."
        )

        return

    if not SEREY_PASSWORD:

        log(
            "❌ SEREY_PASSWORD is missing."
        )

        return

    # --------------------------------------------------------
    # LOAD SYNCED
    # --------------------------------------------------------

    synced = load_synced()

    # Add the 11 permanent skip IDs
    # to the in-memory exclusion set.

    synced_for_skip = set(
        synced
    )

    synced_for_skip.update(
        PERMANENTLY_SKIPPED
    )

    # --------------------------------------------------------
    # GET POSTS
    # --------------------------------------------------------

    posts = get_steem_posts()

    if not posts:

        log(
            "❌ No Steem posts found."
        )

        return

    # --------------------------------------------------------
    # FIND UNSYNCED
    # --------------------------------------------------------

    unsynced = []

    permanently_skipped_count = 0

    already_synced_count = 0

    for post in posts:

        author = post.get(
            "author",
            ""
        )

        permlink = post.get(
            "permlink",
            ""
        )

        post_id = normalize_post_id(
            author,
            permlink
        )

        if not post_id:
            continue

        # --------------------------------------------
        # Permanent old 11
        # --------------------------------------------

        if post_id in PERMANENTLY_SKIPPED:

            permanently_skipped_count += 1

            continue

        # --------------------------------------------
        # Normal synced posts
        # --------------------------------------------

        if post_id in synced:

            already_synced_count += 1

            continue

        unsynced.append(
            post
        )

    # --------------------------------------------------------
    # CORRECT COUNTS
    # --------------------------------------------------------

    log(
        f"Permanent skipped posts found: "
        f"{permanently_skipped_count}"
    )

    log(
        f"Already synced posts found: "
        f"{already_synced_count}"
    )

    log(
        f"Unsynced posts: "
        f"{len(unsynced)}"
    )

    if not unsynced:

        log(
            "Nothing new to publish."
        )

        return

    selected = unsynced[
        :POSTS_PER_RUN
    ]

    log(
        f"Publishing this run: "
        f"{len(selected)}"
    )

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )

        context = browser.new_context(

            viewport={
                "width": 1440,
                "height": 1000,
            },

            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            if not login_serey(page):

                log(
                    "❌ Cannot login to Serey."
                )

                return

            # ------------------------------------------------
            # PUBLISH
            # ------------------------------------------------

            for post in selected:

                author = post.get(
                    "author",
                    ""
                )

                permlink = post.get(
                    "permlink",
                    ""
                )

                post_id = normalize_post_id(
                    author,
                    permlink
                )

                # Safety check
                if post_id in synced:

                    log(
                        f"⏭️ Already synced: "
                        f"{post_id}"
                    )

                    continue

                if post_id in PERMANENTLY_SKIPPED:

                    log(
                        f"⏭️ Permanently skipped: "
                        f"{post_id}"
                    )

                    continue

                success = publish_post(
                    page,
                    post
                )

                # --------------------------------------------
                # ONLY SAVE AFTER REAL SUCCESS
                # --------------------------------------------

                if success:

                    synced.add(
                        post_id
                    )

                    if save_synced(
                        synced
                    ):

                        log(
                            f"✓ SAVED AS SYNCED: "
                            f"{post_id}"
                        )

                else:

                    log(
                        f"❌ FAILED: "
                        f"{post_id}"
                    )

                    log(
                        "⚠️ This post was NOT "
                        "added to synced_posts.json."
                    )

        except Exception as e:

            log(
                f"❌ Unexpected error: {e}"
            )

            try:

                save_debug(page)

            except Exception:
                pass

        finally:

            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass

    log("")
    log(
        "========================================"
    )
    log(
        "SYNC COMPLETED"
    )
    log(
        "========================================"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
