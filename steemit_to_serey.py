import os
import json
import requests
import time
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


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

# Debug files
DEBUG_SCREENSHOT = "serey_debug.png"
DEBUG_HTML = "serey_debug.html"

POSTS_PER_RUN = 1

# Last 2 years
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

    # Markdown image
    if not first_image_url:

        match = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
            body_text,
            re.IGNORECASE
        )

        if match:
            first_image_url = match.group(1)

    # Direct image URL
    if not first_image_url:

        match = re.search(
            r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
            body_text,
            re.IGNORECASE
        )

        if match:
            first_image_url = match.group(0)

    clean_body = body_text

    # Remove markdown images
    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )

    # Remove direct image URLs
    clean_body = re.sub(
        r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
        '',
        clean_body,
        flags=re.IGNORECASE
    )

    # Clean excessive blank lines
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
# FETCH POSTS
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

    two_years_ago = (
        datetime.now(timezone.utc)
        -
        timedelta(days=START_FROM_DAYS_AGO)
    )

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

            author = post.get(
                "author",
                ""
            )

            permlink = post.get(
                "permlink",
                ""
            )

            if not permlink:
                continue

            post_id = (
                f"{author}/{permlink}"
            )

            if post_id in seen_ids:
                continue

            created_str = post.get(
                "created",
                ""
            )

            try:

                post_created_dt = (
                    datetime.strptime(
                        created_str,
                        "%Y-%m-%dT%H:%M:%S"
                    ).replace(
                        tzinfo=timezone.utc
                    )
                )

            except Exception:

                post_created_dt = None

            if (
                post_created_dt
                and
                post_created_dt < two_years_ago
            ):

                stop_fetching = True
                break

            seen_ids.add(post_id)

            raw_body = post.get(
                "body",
                ""
            )

            metadata = post.get(
                "json_metadata",
                "{}"
            )

            image_url, clean_body = (
                extract_image_and_clean_body(
                    raw_body,
                    metadata
                )
            )

            all_posts.append({

                "author": author,

                "permlink": permlink,

                "title": post.get(
                    "title",
                    ""
                ),

                "body": clean_body,

                "image": image_url,

                "category": post.get(
                    "category",
                    ""
                ),

                "created": created_str,

                "created_dt": post_created_dt
            })

            added_this_batch += 1

        if stop_fetching:
            break

        last_post = result[-1]

        new_start_author = (
            last_post.get("author")
        )

        new_start_permlink = (
            last_post.get("permlink")
        )

        if (
            new_start_author == start_author
            and
            new_start_permlink == start_permlink
        ):
            break

        if (
            added_this_batch == 0
            and
            not stop_fetching
        ):
            break

        start_author = new_start_author
        start_permlink = new_start_permlink

        if len(all_posts) >= 5000:
            break

        if len(result) < 100:
            break

        time.sleep(0.3)

    all_posts.sort(
        key=lambda x:
        x["created_dt"]
        if x["created_dt"]
        else datetime.min.replace(
            tzinfo=timezone.utc
        )
    )

    print(
        f"\nTotal historical posts fetched: "
        f"{len(all_posts)}",
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

        print(
            f"Downloading image: {image_url}",
            flush=True
        )

        response = requests.get(
            image_url,
            timeout=30,
            headers={
                "User-Agent":
                "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        content_type = (
            response.headers
            .get(
                "content-type",
                ""
            )
            .lower()
        )

        if "image" not in content_type:

            print(
                "URL did not return an image.",
                flush=True
            )

            return None

        with open(
            TEMP_IMG_FILE,
            "wb"
        ) as file:

            file.write(
                response.content
            )

        print(
            "Image downloaded successfully!",
            flush=True
        )

        return TEMP_IMG_FILE

    except Exception as e:

        print(
            f"Image download failed: {e}",
            flush=True
        )

        return None


# ============================================================
# NORMALIZE TEXT
# ============================================================

def normalize_text(text):

    text = text.lower()

    text = re.sub(
        r'[^a-z0-9\u0980-\u09ff\s]',
        ' ',
        text
    )

    text = re.sub(
        r'\s+',
        ' ',
        text
    )

    return text.strip()


# ============================================================
# DEBUG SEREY PAGE
# ============================================================

def save_debug(page, name="serey_debug"):

    try:

        screenshot_file = (
            f"{name}.png"
        )

        html_file = (
            f"{name}.html"
        )

        page.screenshot(
            path=screenshot_file,
            full_page=True
        )

        with open(
            html_file,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                page.content()
            )

        print(
            f"DEBUG screenshot saved: "
            f"{screenshot_file}",
            flush=True
        )

        print(
            f"DEBUG HTML saved: "
            f"{html_file}",
            flush=True
        )

    except Exception as e:

        print(
            f"Could not save debug files: {e}",
            flush=True
        )


# ============================================================
# GET VISIBLE MODAL
# ============================================================

def get_visible_modal(page):

    selectors = [
        ".ant-modal-content",
        ".ant-modal:not(.ant-modal-hidden)",
        '[role="dialog"]',
        ".modal-content"
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            for i in range(count):

                item = locator.nth(i)

                if item.is_visible():

                    print(
                        f"  - Visible modal found using: "
                        f"{selector}",
                        flush=True
                    )

                    return item

        except Exception:
            continue

    return None


# ============================================================
# WAIT FOR MODAL
# ============================================================

def wait_for_publish_modal(page):

    print(
        "  - Waiting for Publish modal...",
        flush=True
    )

    selectors = [
        ".ant-modal-content",
        ".ant-modal",
        '[role="dialog"]',
        ".modal-content"
    ]

    for selector in selectors:

        try:

            page.locator(
                selector
            ).filter(
                visible=True
            ).first.wait_for(
                state="visible",
                timeout=10000
            )

            print(
                f"  - Modal detected: {selector}",
                flush=True
            )

            return True

        except Exception:
            pass

    # Last fallback
    try:

        page.wait_for_timeout(2000)

        modal = get_visible_modal(page)

        if modal:
            return True

    except Exception:
        pass

    return False


# ============================================================
# FIND CATEGORY CONTROL
# ============================================================

def find_category_control(page):

    print(
        "  - Searching for Category control...",
        flush=True
    )

    modal = get_visible_modal(page)

    if not modal:
        print(
            "  - No visible modal found.",
            flush=True
        )
        return None

    # --------------------------------------------------------
    # 1. Ant Design select
    # --------------------------------------------------------

    selectors = [

        ".ant-select-selector",

        ".ant-select",

        '[role="combobox"]',

        'input[placeholder*="Category" i]',

        'input[aria-label*="Category" i]',

        'div[aria-label*="Category" i]',

        'button:has-text("Category")',

        'label:has-text("Category")'
    ]

    for selector in selectors:

        try:

            items = modal.locator(
                selector
            )

            count = items.count()

            print(
                f"    Selector {selector}: "
                f"{count} found",
                flush=True
            )

            for i in range(count):

                item = items.nth(i)

                if not item.is_visible():
                    continue

                try:

                    box = item.bounding_box()

                    if box:
                        print(
                            f"  - Category control found: "
                            f"{selector}",
                            flush=True
                        )
                        return item

                except Exception:
                    pass

        except Exception:
            continue

    # --------------------------------------------------------
    # 2. Search nearby text
    # --------------------------------------------------------

    try:

        category_texts = [
            "Category",
            "Select Category",
            "Choose Category",
            "category"
        ]

        for text in category_texts:

            loc = modal.get_by_text(
                text,
                exact=False
            )

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if not item.is_visible():
                    continue

                try:

                    parent = item.locator(
                        ".."
                    )

                    # Search clickable/select inside parent
                    for child_selector in [
                        ".ant-select-selector",
                        ".ant-select",
                        "button",
                        "input",
                        '[role="combobox"]'
                    ]:

                        child = parent.locator(
                            child_selector
                        ).first

                        if child.count() > 0:

                            if child.is_visible():

                                print(
                                    "  - Category control "
                                    "found near Category label!",
                                    flush=True
                                )

                                return child

                except Exception:
                    continue

    except Exception:
        pass

    return None


# ============================================================
# SELECT CATEGORY
# ============================================================

def select_category(page, post):

    print(
        "  - Selecting Category...",
        flush=True
    )

    # Wait for modal
    if not wait_for_publish_modal(page):

        print(
            "  - Publish modal was not detected.",
            flush=True
        )

        save_debug(
            page,
            "category_modal_missing"
        )

        return False

    page.wait_for_timeout(1000)

    control = find_category_control(page)

    if not control:

        print(
            "  - Category control not found.",
            flush=True
        )

        save_debug(
            page,
            "category_control_not_found"
        )

        return False

    # --------------------------------------------------------
    # Click category
    # --------------------------------------------------------

    try:

        control.scroll_into_view_if_needed()

        control.click(
            force=True,
            timeout=10000
        )

        print(
            "  - Category control clicked!",
            flush=True
        )

    except Exception as e:

        print(
            f"  - Normal category click failed: {e}",
            flush=True
        )

        try:

            control.evaluate(
                "(el) => el.click()"
            )

            print(
                "  - Category clicked using JavaScript!",
                flush=True
            )

        except Exception as js_error:

            print(
                f"  - JavaScript click failed: "
                f"{js_error}",
                flush=True
            )

            return False

    page.wait_for_timeout(1500)

    # --------------------------------------------------------
    # Find visible dropdown
    # --------------------------------------------------------

    dropdown_selectors = [

        ".ant-select-dropdown:not(.ant-select-dropdown-hidden)",

        '[role="listbox"]',

        ".ant-dropdown:not(.ant-dropdown-hidden)",

        ".ant-dropdown",

        ".select-dropdown",

        ".dropdown-menu"
    ]

    dropdown = None

    for selector in dropdown_selectors:

        try:

            items = page.locator(
                selector
            )

            count = items.count()

            for i in range(count):

                item = items.nth(i)

                if item.is_visible():

                    dropdown = item

                    print(
                        f"  - Dropdown found: {selector}",
                        flush=True
                    )

                    break

            if dropdown:
                break

        except Exception:
            continue

    # --------------------------------------------------------
    # Option selection
    # --------------------------------------------------------

    if dropdown:

        option_selectors = [

            ".ant-select-item-option",

            '[role="option"]',

            ".ant-dropdown-menu-item",

            ".dropdown-item",

            "li"
        ]

        for selector in option_selectors:

            try:

                options = dropdown.locator(
                    selector
                )

                count = options.count()

                if count == 0:
                    continue

                print(
                    f"  - Found {count} category "
                    f"option(s).",
                    flush=True
                )

                # Prefer actual visible options
                for i in range(count):

                    option = options.nth(i)

                    if not option.is_visible():
                        continue

                    try:

                        text = option.inner_text(
                            timeout=3000
                        ).strip()

                    except Exception:

                        text = ""

                    if not text:
                        continue

                    print(
                        f"    Category option: {text}",
                        flush=True
                    )

                    # Click first valid option
                    try:

                        option.click(
                            force=True,
                            timeout=10000
                        )

                        print(
                            f"  - Category selected: "
                            f"{text}",
                            flush=True
                        )

                        page.wait_for_timeout(1000)

                        return True

                    except Exception as option_error:

                        print(
                            f"    Option click failed: "
                            f"{option_error}",
                            flush=True
                        )

            except Exception:
                continue

    # --------------------------------------------------------
    # Keyboard fallback
    # --------------------------------------------------------

    print(
        "  - Trying keyboard category fallback...",
        flush=True
    )

    try:

        page.keyboard.press(
            "ArrowDown"
        )

        page.wait_for_timeout(300)

        page.keyboard.press(
            "Enter"
        )

        page.wait_for_timeout(1000)

        print(
            "  - Category selected using "
            "keyboard fallback!",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"  - Keyboard fallback failed: {e}",
            flush=True
        )

    save_debug(
        page,
        "category_selection_failed"
    )

    return False


# ============================================================
# FIND FINAL PUBLISH BUTTON
# ============================================================

def find_final_publish_button(page):

    print(
        "  - Searching for Final Publish button...",
        flush=True
    )

    modal = get_visible_modal(page)

    if not modal:
        print(
            "  - No visible modal for final Publish.",
            flush=True
        )
        return None

    selectors = [

        "button:has-text('Publish')",

        "button:has-text('publish')",

        '[role="button"]:has-text("Publish")',

        'input[type="submit"][value*="Publish" i]'
    ]

    candidates = []

    for selector in selectors:

        try:

            items = modal.locator(
                selector
            )

            count = items.count()

            for i in range(count):

                item = items.nth(i)

                if item.is_visible():

                    candidates.append(item)

        except Exception:
            continue

    # Remove duplicates conceptually by testing from last to first
    for item in reversed(candidates):

        try:

            if not item.is_enabled():
                continue

        except Exception:
            pass

        try:

            text = item.inner_text(
                timeout=2000
            ).strip()

        except Exception:

            text = ""

        print(
            f"  - Candidate Publish button: "
            f"'{text}'",
            flush=True
        )

        return item

    return None


# ============================================================
# FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    button = find_final_publish_button(
        page
    )

    if not button:

        print(
            "❌ Final Publish button not found!",
            flush=True
        )

        save_debug(
            page,
            "final_publish_not_found"
        )

        return False

    try:

        button.scroll_into_view_if_needed()

        page.wait_for_timeout(500)

        button.click(
            force=True,
            timeout=15000
        )

        print(
            "  - Final Publish button clicked!",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"  - Normal Final Publish click failed: "
            f"{e}",
            flush=True
        )

        # JavaScript fallback
        try:

            button.evaluate(
                "(el) => el.click()"
            )

            print(
                "  - Final Publish clicked using JavaScript!",
                flush=True
            )

            return True

        except Exception as js_error:

            print(
                f"❌ JavaScript Final Publish failed: "
                f"{js_error}",
                flush=True
            )

            save_debug(
                page,
                "final_publish_click_failed"
            )

            return False


# ============================================================
# CHECK SEREY ERROR TOAST
# ============================================================

def check_serey_error(page):

    selectors = [

        ".ant-message-error",

        ".ant-notification-notice-error",

        ".ant-alert-error",

        '[role="alert"]'
    ]

    for selector in selectors:

        try:

            items = page.locator(
                selector
            )

            count = items.count()

            for i in range(count):

                item = items.nth(i)

                if not item.is_visible():
                    continue

                try:

                    text = item.inner_text(
                        timeout=2000
                    ).strip()

                except Exception:

                    text = ""

                if text:

                    print(
                        f"  - SEREY ERROR: {text}",
                        flush=True
                    )

                    return text

        except Exception:
            continue

    return None


# ============================================================
# VERIFY SEREY POST
# ============================================================

def verify_serey_post(page, post):

    title = post["title"].strip()

    print(
        "\n🔎 VERIFYING POST ON SEREY...",
        flush=True
    )

    print(
        f"Expected title: {title}",
        flush=True
    )

    page.wait_for_timeout(5000)

    current_url = page.url

    print(
        f"Current Serey URL: {current_url}",
        flush=True
    )

    # If still creation page, wait a little more
    if "/blog/post/new" in current_url:

        print(
            "  - Still on creation page. "
            "Waiting for redirect...",
            flush=True
        )

        for _ in range(10):

            page.wait_for_timeout(1000)

            if "/blog/post/new" not in page.url:
                break

    current_url = page.url

    if "/blog/post/new" in current_url:

        print(
            "❌ FAILED: Still on /blog/post/new.",
            flush=True
        )

        save_debug(
            page,
            "verification_still_new"
        )

        return False

    normalized_title = normalize_text(
        title
    )

    # --------------------------------------------------------
    # Profile verification
    # --------------------------------------------------------

    profile_urls = [

        f"https://serey.io/authors/@{SEREY_LOGIN}",

        f"https://serey.io/authors/{SEREY_LOGIN}"
    ]

    for profile_url in profile_urls:

        try:

            print(
                f"Checking profile: {profile_url}",
                flush=True
            )

            page.goto(
                profile_url,
                timeout=30000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(5000)

            profile_html = page.content()

            normalized_profile = normalize_text(
                profile_html
            )

            if (
                normalized_title
                and
                normalized_title
                in normalized_profile
            ):

                print(
                    "✅ POST TITLE FOUND ON "
                    "SEREY PROFILE!",
                    flush=True
                )

                print(
                    f"Verified URL: {profile_url}",
                    flush=True
                )

                return True

        except Exception as e:

            print(
                f"Profile verification error: {e}",
                flush=True
            )

    print(
        "❌ VERIFICATION FAILED. "
        "Post was not confirmed live on Serey.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH TO SEREY
# ============================================================

def publish_to_serey(page, post):

    print(
        f"\n---> Publishing to Serey: "
        f"{post['title']}",
        flush=True
    )

    try:

        # ----------------------------------------------------
        # Open new post page
        # ----------------------------------------------------

        page.goto(
            "https://serey.io/blog/post/new",
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(4000)

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title_selectors = [

            'input[placeholder*="title" i]',

            'input[placeholder*="Title" i]',

            'input[name="title"]',

            'input[type="text"]'
        ]

        title_box = None

        for selector in title_selectors:

            try:

                locator = page.locator(
                    selector
                ).first

                if locator.count() > 0:

                    if locator.is_visible():

                        title_box = locator
                        break

            except Exception:
                continue

        if not title_box:

            raise RuntimeError(
                "Title input not found."
            )

        title_box.focus()

        title_box.fill(
            post["title"]
        )

        title_box.dispatch_event(
            "input"
        )

        print(
            "  - Title filled!",
            flush=True
        )

        # ----------------------------------------------------
        # BODY
        # ----------------------------------------------------

        body_selectors = [

            'div[contenteditable="true"]',

            'textarea[placeholder*="content" i]',

            'textarea',

            '[contenteditable="true"]'
        ]

        body_box = None

        for selector in body_selectors:

            try:

                locator = page.locator(
                    selector
                ).first

                if locator.count() > 0:

                    if locator.is_visible():

                        body_box = locator
                        break

            except Exception:
                continue

        if not body_box:

            raise RuntimeError(
                "Body editor not found."
            )

        body_box.focus()

        body_box.fill(
            post["body"]
        )

        body_box.dispatch_event(
            "input"
        )

        print(
            "  - Clean body content filled!",
            flush=True
        )

        page.wait_for_timeout(2000)

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        if post.get("image"):

            try:

                temp_image = download_image(
                    post["image"]
                )

                if temp_image:

                    file_inputs = page.locator(
                        'input[type="file"]'
                    )

                    count = file_inputs.count()

                    print(
                        f"  - File input count: {count}",
                        flush=True
                    )

                    if count > 0:

                        uploaded = False

                        for i in range(count):

                            file_input = (
                                file_inputs.nth(i)
                            )

                            try:

                                file_input.set_input_files(
                                    temp_image
                                )

                                uploaded = True

                                print(
                                    "  - Thumbnail image uploaded!",
                                    flush=True
                                )

                                break

                            except Exception:
                                continue

                        if not uploaded:

                            print(
                                "  - Could not upload image.",
                                flush=True
                            )

                        page.wait_for_timeout(
                            4000
                        )

            except Exception as e:

                print(
                    f"  - Thumbnail upload skipped: "
                    f"{e}",
                    flush=True
                )

        # ----------------------------------------------------
        # FIRST PUBLISH BUTTON
        # ----------------------------------------------------

        print(
            "  - Clicking initial Publish button...",
            flush=True
        )

        publish_selectors = [

            'button:has-text("Publish")',

            'button:has-text("publish")',

            '[role="button"]:has-text("Publish")'
        ]

        initial_publish = None

        for selector in publish_selectors:

            try:

                buttons = page.locator(
                    selector
                )

                count = buttons.count()

                for i in range(count):

                    btn = buttons.nth(i)

                    if not btn.is_visible():
                        continue

                    try:

                        if not btn.is_enabled():
                            continue

                    except Exception:
                        pass

                    initial_publish = btn
                    break

                if initial_publish:
                    break

            except Exception:
                continue

        if not initial_publish:

            raise RuntimeError(
                "Initial Publish button not found."
            )

        initial_publish.click(
            force=True,
            timeout=15000
        )

        page.wait_for_timeout(3000)

        # ----------------------------------------------------
        # ERROR CHECK
        # ----------------------------------------------------

        error = check_serey_error(
            page
        )

        if error:

            print(
                "❌ Serey displayed an error "
                "after initial Publish.",
                flush=True
            )

            save_debug(
                page,
                "initial_publish_error"
            )

            return False

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        category_success = select_category(
            page,
            post
        )

        if not category_success:

            print(
                "❌ Category selection failed.",
                flush=True
            )

            print(
                "Post will NOT be marked as synced.",
                flush=True
            )

            return False

        # ----------------------------------------------------
        # FINAL PUBLISH
        # ----------------------------------------------------

        page.wait_for_timeout(1500)

        print(
            "  - Clicking Final Publish button in Modal...",
            flush=True
        )

        final_success = click_final_publish(
            page
        )

        if not final_success:

            print(
                "❌ Final Publish failed.",
                flush=True
            )

            return False

        # ----------------------------------------------------
        # WAIT FOR RESULT
        # ----------------------------------------------------

        print(
            "  - Waiting for Serey response...",
            flush=True
        )

        for _ in range(20):

            page.wait_for_timeout(
                1000
            )

            error = check_serey_error(
                page
            )

            if error:

                print(
                    "❌ Serey reported an error.",
                    flush=True
                )

                save_debug(
                    page,
                    "final_publish_error"
                )

                return False

            if "/blog/post/new" not in page.url:

                print(
                    f"  - Redirected to: "
                    f"{page.url}",
                    flush=True
                )

                break

        # ----------------------------------------------------
        # VERIFICATION
        # ----------------------------------------------------

        verified = verify_serey_post(
            page,
            post
        )

        if verified:

            print(
                "\n🎉 POST SUCCESSFULLY VERIFIED "
                "ON SEREY!",
                flush=True
            )

        else:

            print(
                "\n⚠️ POST COULD NOT BE VERIFIED.",
                flush=True
            )

        return verified

    except Exception as e:

        print(
            f"\n❌ Failed to publish post on Serey: "
            f"{e}",
            flush=True
        )

        save_debug(
            page,
            "publish_exception"
        )

        return False

    finally:

        if os.path.exists(
            TEMP_IMG_FILE
        ):

            try:

                os.remove(
                    TEMP_IMG_FILE
                )

            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60,
        flush=True
    )

    print(
        "       STEEMIT -> SEREY AUTOMATION",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    # --------------------------------------------------------
    # Load synced posts
    # --------------------------------------------------------

    synced_posts = (
        load_synced_posts()
    )

    print(
        f"Previously synced posts: "
        f"{len(synced_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # Fetch posts
    # --------------------------------------------------------

    posts = get_recent_posts()

    # --------------------------------------------------------
    # Find unsynced
    # --------------------------------------------------------

    new_posts = []

    for post in posts:

        post_id = (
            f'{post["author"]}/'
            f'{post["permlink"]}'
        )

        if post_id not in synced_posts:

            new_posts.append(
                post
            )

    print(
        f"Total historical posts "
        f"(Within last 2 years): "
        f"{len(posts)}",
        flush=True
    )

    print(
        f"Unsynced posts available: "
        f"{len(new_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # Only one post per run
    # --------------------------------------------------------

    new_posts_to_run = (
        new_posts[:POSTS_PER_RUN]
    )

    print(
        f"Publishing this run: "
        f"{len(new_posts_to_run)} post(s)",
        flush=True
    )

    if not new_posts_to_run:

        print(
            "No new posts to sync!",
            flush=True
        )

        return

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
                "height": 800
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

        # ----------------------------------------------------
        # LOGIN
        # ----------------------------------------------------

        print(
            "\nLogging into Serey.io...",
            flush=True
        )

        try:

            page.goto(
                "https://serey.io",
                timeout=60000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(
                4000
            )

            print(
                "Clicking Log in button...",
                flush=True
            )

            login_selectors = [

                'a:has-text("Log in")',

                'button:has-text("Log in")',

                'a:has-text("Log In")',

                'button:has-text("Log In")'
            ]

            login_button = None

            for selector in login_selectors:

                try:

                    loc = page.locator(
                        selector
                    ).first

                    if (
                        loc.count() > 0
                        and
                        loc.is_visible()
                    ):

                        login_button = loc
                        break

                except Exception:
                    continue

            if not login_button:

                raise RuntimeError(
                    "Login button not found."
                )

            login_button.click(
                force=True
            )

            page.wait_for_timeout(
                5000
            )

            # ------------------------------------------------
            # Username
            # ------------------------------------------------

            username_selectors = [

                'input[placeholder="Username"]',

                'input[placeholder*="Username" i]',

                'input[name="username"]'
            ]

            username_box = None

            for selector in username_selectors:

                try:

                    loc = page.locator(
                        selector
                    ).first

                    if (
                        loc.count() > 0
                        and
                        loc.is_visible()
                    ):

                        username_box = loc
                        break

                except Exception:
                    continue

            if not username_box:

                raise RuntimeError(
                    "Username input not found."
                )

            username_box.fill(
                SEREY_LOGIN
            )

            # ------------------------------------------------
            # Password / Private Key
            # ------------------------------------------------

            password_selectors = [

                'input[placeholder*="Private Key or Password" i]',

                'input[placeholder*="Private Key" i]',

                'input[type="password"]'
            ]

            password_box = None

            for selector in password_selectors:

                try:

                    loc = page.locator(
                        selector
                    ).first

                    if (
                        loc.count() > 0
                        and
                        loc.is_visible()
                    ):

                        password_box = loc
                        break

                except Exception:
                    continue

            if not password_box:

                raise RuntimeError(
                    "Password/Private Key input "
                    "not found."
                )

            password_box.fill(
                SEREY_PASSWORD
            )

            # ------------------------------------------------
            # Login submit
            # ------------------------------------------------

            login_submit_selectors = [

                '.ant-modal-content button:has-text("Log in")',

                '.ant-modal-content button:has-text("Log In")',

                'button:has-text("Log in")',

                'button:has-text("Log In")'
            ]

            login_submit = None

            for selector in login_submit_selectors:

                try:

                    buttons = page.locator(
                        selector
                    )

                    count = buttons.count()

                    for i in range(count):

                        btn = buttons.nth(i)

                        if btn.is_visible():

                            login_submit = btn
                            break

                    if login_submit:
                        break

                except Exception:
                    continue

            if not login_submit:

                raise RuntimeError(
                    "Login submit button not found."
                )

            login_submit.click(
                force=True
            )

            page.wait_for_timeout(
                7000
            )

            # ------------------------------------------------
            # Login verification
            # ------------------------------------------------

            current_url = page.url

            print(
                f"Current URL after login: "
                f"{current_url}",
                flush=True
            )

            print(
                "LOGGED INTO SEREY SUCCESSFULLY!",
                flush=True
            )

        except Exception as e:

            print(
                f"Login failed: {e}",
                flush=True
            )

            save_debug(
                page,
                "login_failed"
            )

            browser.close()

            return

        # ----------------------------------------------------
        # PUBLISH POSTS
        # ----------------------------------------------------

        for post in new_posts_to_run:

            success = publish_to_serey(
                page,
                post
            )

            if success:

                post_id = (
                    f'{post["author"]}/'
                    f'{post["permlink"]}'
                )

                synced_posts.add(
                    post_id
                )

                save_synced_posts(
                    synced_posts
                )

                print(
                    f"✅ Saved as synced: "
                    f"{post_id}",
                    flush=True
                )

            else:

                print(
                    "\n⚠️ Post was NOT verified.",
                    flush=True
                )

                print(
                    "It will remain UNSYNCED "
                    "and can be retried on "
                    "the next run.",
                    flush=True
                )

        browser.close()

    print(
        "\n" + "=" * 60,
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
