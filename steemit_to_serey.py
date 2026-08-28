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
                timeout=30
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise RuntimeError(str(data["error"]))

            return data["result"]

        except Exception as e:

            last_error = e

            print(
                f"RPC failed: {node} -> {e}",
                flush=True
            )

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed. Last error: {last_error}"
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
        ) as f:

            data = json.load(f)

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
    ) as f:

        json.dump(
            sorted(posts),
            f,
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

        meta = json.loads(json_metadata_str)

        if (
            isinstance(meta, dict)
            and isinstance(meta.get("image"), list)
            and meta["image"]
        ):

            first_image_url = meta["image"][0]

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
# FETCH STEEM POSTS
# ============================================================

def get_recent_posts():

    print(
        f"\nFetching historical posts from Steemit: "
        f"@{STEEM_USERNAME}",
        flush=True
    )

    all_posts = []
    seen_ids = set()

    start_author = None
    start_permlink = None

    page_number = 0

    two_years_ago = (
        datetime.now(timezone.utc)
        - timedelta(days=START_FROM_DAYS_AGO)
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

            author = post.get("author", "")
            permlink = post.get("permlink", "")

            if not permlink:
                continue

            post_id = f"{author}/{permlink}"

            if post_id in seen_ids:
                continue

            created_str = post.get("created", "")

            try:

                created_dt = datetime.strptime(
                    created_str,
                    "%Y-%m-%dT%H:%M:%S"
                ).replace(
                    tzinfo=timezone.utc
                )

            except Exception:

                created_dt = None

            if (
                created_dt
                and created_dt < two_years_ago
            ):

                stop_fetching = True
                break

            seen_ids.add(post_id)

            raw_body = post.get("body", "")
            metadata = post.get("json_metadata", "{}")

            image_url, clean_body = (
                extract_image_and_clean_body(
                    raw_body,
                    metadata
                )
            )

            all_posts.append({
                "author": author,
                "permlink": permlink,
                "title": post.get("title", ""),
                "body": clean_body,
                "image": image_url,
                "category": post.get("category", ""),
                "created": created_str,
                "created_dt": created_dt
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

        if added_this_batch == 0:
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
# IMAGE DOWNLOAD
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
            .get("content-type", "")
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
        ) as f:

            f.write(response.content)

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
# DEBUG
# ============================================================

def save_debug(page, name="serey_debug"):

    try:

        page.screenshot(
            path=f"{name}.png",
            full_page=True
        )

        with open(
            f"{name}.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(page.content())

        print(
            f"DEBUG screenshot saved: {name}.png",
            flush=True
        )

        print(
            f"DEBUG HTML saved: {name}.html",
            flush=True
        )

    except Exception as e:

        print(
            f"Could not save debug files: {e}",
            flush=True
        )


# ============================================================
# VISIBLE MODAL
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

            loc = page.locator(selector)

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if item.is_visible():

                    return item

        except Exception:
            continue

    return None


# ============================================================
# WAIT MODAL
# ============================================================

def wait_for_publish_modal(page):

    print(
        "  - Waiting for Publish modal...",
        flush=True
    )

    for _ in range(20):

        modal = get_visible_modal(page)

        if modal:

            print(
                "  - Publish modal detected!",
                flush=True
            )

            return modal

        page.wait_for_timeout(500)

    return None


# ============================================================
# CATEGORY — NEW ROBUST METHOD
# ============================================================

def find_category_area(page, modal):

    print(
        "  - Inspecting modal for Category...",
        flush=True
    )

    # --------------------------------------------------------
    # First: inspect ALL visible text inside modal
    # --------------------------------------------------------

    try:

        text = modal.inner_text(
            timeout=5000
        )

        print(
            "  - Modal text preview:",
            flush=True
        )

        print(
            text[:3000],
            flush=True
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # Search elements containing category text
    # --------------------------------------------------------

    category_words = [
        "category",
        "categories",
        "select category",
        "choose category"
    ]

    for word in category_words:

        try:

            elements = modal.get_by_text(
                word,
                exact=False
            )

            count = elements.count()

            print(
                f"  - Text '{word}': {count} element(s)",
                flush=True
            )

            for i in range(count):

                el = elements.nth(i)

                if not el.is_visible():
                    continue

                # Try current element
                try:

                    box = el.bounding_box()

                    if box:

                        print(
                            f"  - Category text found: '{word}'",
                            flush=True
                        )

                except Exception:
                    pass

                # Parent levels
                for level in range(1, 6):

                    try:

                        parent = el

                        for _ in range(level):
                            parent = parent.locator("..")

                        if not parent.is_visible():
                            continue

                        # Look for clickable elements
                        candidates = parent.locator(
                            "button, input, [role='button'], "
                            "[role='combobox'], "
                            ".ant-select, "
                            ".ant-select-selector, "
                            "div"
                        )

                        candidate_count = candidates.count()

                        for j in range(candidate_count):

                            candidate = candidates.nth(j)

                            if not candidate.is_visible():
                                continue

                            try:

                                box = candidate.bounding_box()

                                if not box:
                                    continue

                                # Avoid returning huge parent containers
                                width = box.get("width", 0)
                                height = box.get("height", 0)

                                if (
                                    width > 20
                                    and
                                    height > 15
                                    and
                                    width < 1000
                                    and
                                    height < 300
                                ):

                                    print(
                                        "  - Possible Category control "
                                        f"found at parent level {level}",
                                        flush=True
                                    )

                                    return candidate

                            except Exception:
                                continue

                    except Exception:
                        continue

        except Exception:
            continue

    return None


# ============================================================
# CATEGORY CLICK + SELECT
# ============================================================

def select_category(page, post):

    print(
        "\n  - Selecting Category...",
        flush=True
    )

    modal = wait_for_publish_modal(page)

    if not modal:

        print(
            "❌ Publish modal not found.",
            flush=True
        )

        save_debug(
            page,
            "category_modal_missing"
        )

        return False

    page.wait_for_timeout(1000)

    control = find_category_area(
        page,
        modal
    )

    if not control:

        print(
            "❌ Category control not found.",
            flush=True
        )

        save_debug(
            page,
            "category_control_not_found"
        )

        return False

    # --------------------------------------------------------
    # Click
    # --------------------------------------------------------

    try:

        control.scroll_into_view_if_needed()

    except Exception:
        pass

    clicked = False

    try:

        control.click(
            force=True,
            timeout=10000
        )

        clicked = True

        print(
            "  - Category area clicked!",
            flush=True
        )

    except Exception as e:

        print(
            f"  - Normal category click failed: {e}",
            flush=True
        )

    if not clicked:

        try:

            control.evaluate(
                "(el) => el.click()"
            )

            clicked = True

            print(
                "  - Category clicked using JavaScript!",
                flush=True
            )

        except Exception as e:

            print(
                f"  - JavaScript click failed: {e}",
                flush=True
            )

    if not clicked:
        return False

    page.wait_for_timeout(1500)

    # --------------------------------------------------------
    # Find dropdown anywhere on page
    # --------------------------------------------------------

    dropdown_selectors = [
        ".ant-select-dropdown",
        '[role="listbox"]',
        ".ant-dropdown",
        ".dropdown-menu",
        ".select-dropdown",
        "ul"
    ]

    dropdown = None

    for selector in dropdown_selectors:

        try:

            loc = page.locator(selector)

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if not item.is_visible():
                    continue

                try:

                    box = item.bounding_box()

                    if box:

                        dropdown = item

                        print(
                            f"  - Dropdown found: {selector}",
                            flush=True
                        )

                        break

                except Exception:
                    continue

            if dropdown:
                break

        except Exception:
            continue

    # --------------------------------------------------------
    # Find category options
    # --------------------------------------------------------

    if dropdown:

        option_selectors = [
            ".ant-select-item-option",
            '[role="option"]',
            ".ant-dropdown-menu-item",
            ".dropdown-item",
            "li",
            "button"
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
                    f"  - {count} dropdown option(s) found.",
                    flush=True
                )

                for i in range(count):

                    option = options.nth(i)

                    if not option.is_visible():
                        continue

                    try:

                        text = option.inner_text(
                            timeout=2000
                        ).strip()

                    except Exception:

                        text = ""

                    if not text:
                        continue

                    print(
                        f"    Option: {text}",
                        flush=True
                    )

                    try:

                        option.click(
                            force=True,
                            timeout=8000
                        )

                        print(
                            f"  ✅ Category selected: {text}",
                            flush=True
                        )

                        page.wait_for_timeout(1000)

                        return True

                    except Exception:
                        continue

            except Exception:
                continue

    # --------------------------------------------------------
    # Generic visible option search
    # --------------------------------------------------------

    print(
        "  - Trying generic visible category options...",
        flush=True
    )

    try:

        visible_texts = [
            "Sports",
            "Sport",
            "Lifestyle",
            "Technology",
            "Education",
            "News",
            "Entertainment",
            "Health",
            "Travel",
            "Other"
        ]

        for text in visible_texts:

            candidates = page.get_by_text(
                text,
                exact=True
            )

            count = candidates.count()

            for i in range(count):

                candidate = candidates.nth(i)

                if not candidate.is_visible():
                    continue

                try:

                    candidate.click(
                        force=True,
                        timeout=5000
                    )

                    print(
                        f"  ✅ Category selected: {text}",
                        flush=True
                    )

                    page.wait_for_timeout(1000)

                    return True

                except Exception:
                    continue

    except Exception:
        pass

    # --------------------------------------------------------
    # Keyboard fallback
    # --------------------------------------------------------

    print(
        "  - Trying keyboard category fallback...",
        flush=True
    )

    try:

        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)

        print(
            "  - Category selected using keyboard.",
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
# FIND PUBLISH BUTTON
# ============================================================

def find_publish_buttons(page, container=None):

    if container is None:
        container = page

    selectors = [
        "button",
        '[role="button"]',
        'input[type="submit"]'
    ]

    buttons = []

    for selector in selectors:

        try:

            loc = container.locator(selector)

            count = loc.count()

            for i in range(count):

                btn = loc.nth(i)

                if not btn.is_visible():
                    continue

                try:

                    text = btn.inner_text(
                        timeout=1000
                    ).strip()

                except Exception:

                    text = ""

                if (
                    "publish" in text.lower()
                    or
                    (
                        selector.startswith("input")
                        and
                        "publish"
                        in btn.get_attribute("value").lower()
                    )
                ):

                    buttons.append(btn)

        except Exception:
            continue

    return buttons


# ============================================================
# FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    print(
        "  - Searching for Final Publish button...",
        flush=True
    )

    modal = get_visible_modal(page)

    if not modal:

        print(
            "❌ No visible modal.",
            flush=True
        )

        save_debug(
            page,
            "final_modal_missing"
        )

        return False

    buttons = find_publish_buttons(
        page,
        modal
    )

    print(
        f"  - Publish button candidates: {len(buttons)}",
        flush=True
    )

    if not buttons:

        save_debug(
            page,
            "final_publish_not_found"
        )

        return False

    # Last Publish button is normally final confirmation
    for button in reversed(buttons):

        try:

            if not button.is_enabled():
                continue

        except Exception:
            pass

        try:

            text = button.inner_text(
                timeout=1000
            ).strip()

        except Exception:

            text = "Publish"

        print(
            f"  - Clicking Publish button: '{text}'",
            flush=True
        )

        try:

            button.scroll_into_view_if_needed()

        except Exception:
            pass

        try:

            button.click(
                force=True,
                timeout=15000
            )

            print(
                "  ✅ Final Publish clicked!",
                flush=True
            )

            return True

        except Exception as e:

            print(
                f"  - Button click failed: {e}",
                flush=True
            )

            try:

                button.evaluate(
                    "(el) => el.click()"
                )

                print(
                    "  ✅ Final Publish clicked using JS!",
                    flush=True
                )

                return True

            except Exception:
                continue

    return False


# ============================================================
# SEREY ERROR
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

            items = page.locator(selector)

            count = items.count()

            for i in range(count):

                item = items.nth(i)

                if not item.is_visible():
                    continue

                try:

                    text = item.inner_text(
                        timeout=1000
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
# VERIFY POST
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

    # If still new-post page
    if "/blog/post/new" in current_url:

        print(
            "  - Waiting for redirect...",
            flush=True
        )

        for _ in range(15):

            page.wait_for_timeout(1000)

            if "/blog/post/new" not in page.url:
                break

    current_url = page.url

    if "/blog/post/new" in current_url:

        print(
            "❌ Still on /blog/post/new.",
            flush=True
        )

        save_debug(
            page,
            "verification_still_new"
        )

        return False

    normalized_title = normalize_text(title)

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

            page.wait_for_timeout(4000)

            html = page.content()

            if normalized_title in normalize_text(html):

                print(
                    "✅ POST TITLE FOUND ON SEREY PROFILE!",
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
        "❌ Verification failed.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH ONE POST
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

        title_box = None

        title_selectors = [
            'input[name="title"]',
            'input[placeholder*="title" i]',
            'input[placeholder*="Title" i]',
            'input[type="text"]'
        ]

        for selector in title_selectors:

            try:

                loc = page.locator(selector)

                count = loc.count()

                for i in range(count):

                    item = loc.nth(i)

                    if item.is_visible():

                        title_box = item
                        break

                if title_box:
                    break

            except Exception:
                continue

        if not title_box:

            raise RuntimeError(
                "Title input not found."
            )

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

        body_box = None

        body_selectors = [
            'div[contenteditable="true"]',
            'textarea[placeholder*="content" i]',
            'textarea',
            '[contenteditable="true"]'
        ]

        for selector in body_selectors:

            try:

                loc = page.locator(selector)

                count = loc.count()

                for i in range(count):

                    item = loc.nth(i)

                    if item.is_visible():

                        body_box = item
                        break

                if body_box:
                    break

            except Exception:
                continue

        if not body_box:

            raise RuntimeError(
                "Body editor not found."
            )

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

        page.wait_for_timeout(1500)

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        if post.get("image"):

            try:

                temp_image = download_image(
                    post["image"]
                )

                if temp_image:

                    inputs = page.locator(
                        'input[type="file"]'
                    )

                    count = inputs.count()

                    print(
                        f"  - File input count: {count}",
                        flush=True
                    )

                    uploaded = False

                    for i in range(count):

                        try:

                            inputs.nth(i).set_input_files(
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

                    if uploaded:
                        page.wait_for_timeout(4000)

            except Exception as e:

                print(
                    f"  - Image upload skipped: {e}",
                    flush=True
                )

        # ----------------------------------------------------
        # INITIAL PUBLISH
        # ----------------------------------------------------

        print(
            "  - Clicking initial Publish button...",
            flush=True
        )

        buttons = find_publish_buttons(page)

        initial_publish = None

        for button in buttons:

            try:

                text = button.inner_text(
                    timeout=1000
                ).strip()

            except Exception:

                text = ""

            if button.is_visible():

                initial_publish = button

                print(
                    f"  - Initial Publish found: '{text}'",
                    flush=True
                )

                break

        if not initial_publish:

            raise RuntimeError(
                "Initial Publish button not found."
            )

        initial_publish.click(
            force=True,
            timeout=15000
        )

        page.wait_for_timeout(2500)

        error = check_serey_error(page)

        if error:

            save_debug(
                page,
                "initial_publish_error"
            )

            return False

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        if not select_category(page, post):

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

        page.wait_for_timeout(1000)

        print(
            "  - Clicking Final Publish button in Modal...",
            flush=True
        )

        if not click_final_publish(page):

            print(
                "❌ Final Publish failed.",
                flush=True
            )

            return False

        # ----------------------------------------------------
        # WAIT
        # ----------------------------------------------------

        print(
            "  - Waiting for Serey response...",
            flush=True
        )

        redirected = False

        for _ in range(20):

            page.wait_for_timeout(1000)

            error = check_serey_error(page)

            if error:

                save_debug(
                    page,
                    "final_publish_error"
                )

                return False

            if "/blog/post/new" not in page.url:

                redirected = True

                print(
                    f"  - Redirected to: {page.url}",
                    flush=True
                )

                break

        # ----------------------------------------------------
        # VERIFY
        # ----------------------------------------------------

        verified = verify_serey_post(
            page,
            post
        )

        if verified:

            print(
                "\n🎉 POST SUCCESSFULLY VERIFIED ON SEREY!",
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
            f"\n❌ Failed to publish post on Serey: {e}",
            flush=True
        )

        save_debug(
            page,
            "publish_exception"
        )

        return False

    finally:

        if os.path.exists(TEMP_IMG_FILE):

            try:
                os.remove(TEMP_IMG_FILE)
            except Exception:
                pass


# ============================================================
# LOGIN
# ============================================================

def login_to_serey(page):

    print(
        "\nLogging into Serey.io...",
        flush=True
    )

    page.goto(
        "https://serey.io",
        timeout=60000,
        wait_until="domcontentloaded"
    )

    page.wait_for_timeout(4000)

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

            loc = page.locator(selector)

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if item.is_visible():

                    login_button = item
                    break

            if login_button:
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

    page.wait_for_timeout(3000)

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    username_box = None

    username_selectors = [
        'input[name="username"]',
        'input[placeholder*="Username" i]',
        'input[placeholder*="username" i]'
    ]

    for selector in username_selectors:

        try:

            loc = page.locator(selector)

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if item.is_visible():

                    username_box = item
                    break

            if username_box:
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

    # --------------------------------------------------------
    # Password
    # --------------------------------------------------------

    password_box = None

    password_selectors = [
        'input[placeholder*="Private Key or Password" i]',
        'input[placeholder*="Private Key" i]',
        'input[type="password"]'
    ]

    for selector in password_selectors:

        try:

            loc = page.locator(selector)

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if item.is_visible():

                    password_box = item
                    break

            if password_box:
                break

        except Exception:
            continue

    if not password_box:

        raise RuntimeError(
            "Password/Private Key input not found."
        )

    password_box.fill(
        SEREY_PASSWORD
    )

    # --------------------------------------------------------
    # Submit
    # --------------------------------------------------------

    submit_selectors = [
        '.ant-modal-content button:has-text("Log in")',
        '.ant-modal-content button:has-text("Log In")',
        'button:has-text("Log in")',
        'button:has-text("Log In")'
    ]

    submit_button = None

    for selector in submit_selectors:

        try:

            loc = page.locator(selector)

            count = loc.count()

            for i in range(count):

                item = loc.nth(i)

                if item.is_visible():

                    submit_button = item
                    break

            if submit_button:
                break

        except Exception:
            continue

    if not submit_button:

        raise RuntimeError(
            "Login submit button not found."
        )

    submit_button.click(
        force=True
    )

    page.wait_for_timeout(7000)

    print(
        f"Current URL after login: {page.url}",
        flush=True
    )

    # Check obvious login errors
    error = check_serey_error(page)

    if error:

        raise RuntimeError(
            f"Serey login error: {error}"
        )

    print(
        "LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
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
        "       STEEMIT -> SEREY AUTOMATION",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    synced_posts = load_synced_posts()

    print(
        f"Previously synced posts: {len(synced_posts)}",
        flush=True
    )

    posts = get_recent_posts()

    new_posts = []

    for post in posts:

        post_id = (
            f'{post["author"]}/'
            f'{post["permlink"]}'
        )

        if post_id not in synced_posts:

            new_posts.append(post)

    print(
        f"Total historical posts "
        f"(Within last 2 years): {len(posts)}",
        flush=True
    )

    print(
        f"Unsynced posts available: {len(new_posts)}",
        flush=True
    )

    new_posts_to_run = new_posts[
        :POSTS_PER_RUN
    ]

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
                "Chrome/151.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            login_to_serey(page)

        except Exception as e:

            print(
                f"❌ Login failed: {e}",
                flush=True
            )

            save_debug(
                page,
                "login_failed"
            )

            browser.close()

            return

        # ----------------------------------------------------
        # PUBLISH
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
                    f"✅ Saved as synced: {post_id}",
                    flush=True
                )

            else:

                print(
                    "\n⚠️ Post was NOT verified.",
                    flush=True
                )

                print(
                    "It will remain UNSYNCED "
                    "and can be retried on the next run.",
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
