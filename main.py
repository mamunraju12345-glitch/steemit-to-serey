import os
import re
import json
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# STEEMIT → SEREY AUTO SYNC
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY = "https://bengali.serey.io"

NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"

TEMP_IMAGE = "temp_image.jpg"

# প্রতি run-এ সর্বোচ্চ ১টি post
POSTS_PER_RUN = 1

# শুধুমাত্র গত ৩০ দিনের post
DAYS_TO_CHECK = 30

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.steememory.com",
    "https://api.steem.house",
]


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def load_synced():
    if not os.path.exists(SYNC_FILE):
        return {}

    try:
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

        return {}

    except Exception as e:
        print(f"⚠️ Could not read {SYNC_FILE}: {e}")
        return {}


def save_synced(data):
    temp_file = SYNC_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(temp_file, SYNC_FILE)


# ============================================================
# STEEM API
# ============================================================

def steem_request(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    last_error = None

    for node in STEEM_NODES:

        try:
            print(f"Trying Steem node: {node}")

            response = requests.post(
                node,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            if "result" in data:
                return data["result"]

            print("⚠️ Steem response has no result")

        except Exception as e:
            last_error = e
            print(f"⚠️ Node failed: {e}")

    raise RuntimeError(
        f"All Steem nodes failed. Last error: {last_error}"
    )


# ============================================================
# GET ONLY LAST 30 DAYS POSTS
# ============================================================

def get_posts():

    print()
    print("============================================")
    print("STEEMIT POST DISCOVERY")
    print("============================================")

    print(f"Author: @{STEEM_USERNAME}")
    print(f"Checking last {DAYS_TO_CHECK} days only")

    one_month_ago = datetime.utcnow() - timedelta(
        days=DAYS_TO_CHECK
    )

    posts = []

    start_author = STEEM_USERNAME
    start_permlink = ""

    checked = 0

    while True:

        try:

            batch = steem_request(
                "condenser_api.get_discussions_by_blog",
                [
                    {
                        "tag": STEEM_USERNAME,
                        "limit": 100,
                        "start_author": start_author,
                        "start_permlink": start_permlink,
                    }
                ],
            )

        except Exception as e:

            print(f"❌ Could not get Steemit posts: {e}")
            break

        if not batch:
            break

        for post in batch:

            author = clean_text(post.get("author"))
            permlink = clean_text(post.get("permlink"))
            created_string = clean_text(post.get("created"))

            if not author or not permlink:
                continue

            if author.lower() != STEEM_USERNAME.lower():
                continue

            if not created_string:
                continue

            try:
                # Steem date example:
                # 2026-09-04T10:20:00
                created = datetime.fromisoformat(
                    created_string.replace("Z", "")
                )

            except Exception:
                print(
                    f"⚠️ Could not parse date: {created_string}"
                )
                continue

            # পুরনো post এলে এখানেই stop
            if created < one_month_ago:
                print(
                    f"Reached posts older than {DAYS_TO_CHECK} days."
                )

                # Newest-first response হওয়ায় break করা safe
                return sorted(
                    posts,
                    key=lambda x: x["created"],
                )

            post_data = {
                "author": author,
                "permlink": permlink,
                "created": created,
                "created_string": created_string,
                "title": clean_text(post.get("title")),
                "body": post.get("body") or "",
                "json_metadata": post.get("json_metadata") or "",
                "url": (
                    f"https://steemit.com/"
                    f"@{author}/{permlink}"
                ),
            }

            posts.append(post_data)

        checked += len(batch)

        print(
            f"Checked {checked} Steemit entries..."
        )

        if len(batch) < 100:
            break

        last = batch[-1]

        start_author = last.get("author", "")
        start_permlink = last.get("permlink", "")

        if not start_author or not start_permlink:
            break

        time.sleep(0.5)

    posts = sorted(
        posts,
        key=lambda x: x["created"],
    )

    print()
    print(f"Posts found in last {DAYS_TO_CHECK} days: {len(posts)}")

    for p in posts:
        print(
            f" - {p['created_string']} | "
            f"{p['permlink']} | "
            f"{p['title']}"
        )

    return posts


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def extract_image(post):

    body = post.get("body", "")

    metadata = post.get("json_metadata", "")

    # --------------------------------------------------------
    # First check body for markdown images
    # --------------------------------------------------------

    match = re.search(
        r'!\[[^\]]*\]\((https?://[^)\s]+)',
        body,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    # --------------------------------------------------------
    # Check metadata
    # --------------------------------------------------------

    if metadata:

        try:

            if isinstance(metadata, str):
                meta = json.loads(metadata)
            else:
                meta = metadata

            image_list = meta.get("image", [])

            if isinstance(image_list, list):

                for image in image_list:

                    if isinstance(image, str):
                        if image.startswith("http"):
                            return image

        except Exception:
            pass

    # --------------------------------------------------------
    # Check HTML img src
    # --------------------------------------------------------

    match = re.search(
        r'<img[^>]+src=["\']([^"\']+)["\']',
        body,
        re.IGNORECASE,
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
        return None

    try:

        print()
        print(f"Downloading image:")
        print(image_url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/120 Safari/537.36"
            )
        }

        response = requests.get(
            image_url,
            headers=headers,
            timeout=60,
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "content-type",
            ""
        ).lower()

        if "image" not in content_type:

            print(
                f"⚠️ URL did not return image. "
                f"Content-Type: {content_type}"
            )

            return None

        with open(TEMP_IMAGE, "wb") as f:
            f.write(response.content)

        print(
            f"✓ Image downloaded "
            f"({len(response.content)} bytes)"
        )

        return TEMP_IMAGE

    except Exception as e:

        print(
            f"⚠️ Image download failed: {e}"
        )

        return None


# ============================================================
# REAL SEREY URL DETECTION
# ============================================================

def is_real_serey_post_url(url):

    if not url:
        return False

    url = url.strip()

    if not url.startswith(SEREY):
        return False

    # Serey public post format:
    #
    # https://bengali.serey.io/authors/username/slug
    #
    if re.search(
        r"https://[^/]+\.serey\.io/authors/[^/]+/[^/?#]+",
        url,
        re.IGNORECASE,
    ):
        return True

    # Also allow main serey.io
    if re.search(
        r"https://serey\.io/authors/[^/]+/[^/?#]+",
        url,
        re.IGNORECASE,
    ):
        return True

    return False


def extract_real_post_url(text):

    if not text:
        return None

    # Find author URLs
    matches = re.findall(
        r'https://[^\s"\'<>]+/authors/[^\s"\'<>]+',
        text,
        re.IGNORECASE,
    )

    for url in matches:

        # Remove punctuation
        url = url.rstrip(
            ".,);]}>\"'"
        )

        if is_real_serey_post_url(url):
            return url

    return None


def find_url_in_text(text):

    if not text:
        return None

    url = extract_real_post_url(text)

    if url:
        return url

    return None


# ============================================================
# FIND POST LINK IN PAGE
# ============================================================

def find_post_link(page):

    try:

        links = page.locator(
            'a[href*="/authors/"]'
        )

        count = links.count()

        print(
            f"Author post links found in DOM: {count}"
        )

        for i in range(min(count, 100)):

            try:

                href = links.nth(i).get_attribute(
                    "href"
                )

                if not href:
                    continue

                full_url = urljoin(
                    SEREY,
                    href,
                )

                if is_real_serey_post_url(full_url):

                    print(
                        f"✓ Real post link found: "
                        f"{full_url}"
                    )

                    return full_url

            except Exception:
                continue

    except Exception:
        pass

    return None


# ============================================================
# SEARCH AUTHOR PAGE FOR NEWEST POST
# ============================================================

def search_author_page(page):

    print()
    print("Searching Serey author page...")

    try:

        author_url = (
            f"{SEREY}/authors/"
            f"{SEREY_LOGIN}"
        )

        print(
            f"Author page: {author_url}"
        )

        response = page.goto(
            author_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        time.sleep(5)

        current = page.url

        print(
            f"Author page current URL: {current}"
        )

        if is_real_serey_post_url(current):
            return current

        link = find_post_link(page)

        if link:
            return link

        html = page.content()

        url = extract_real_post_url(html)

        if url:
            return url

    except Exception as e:

        print(
            f"⚠️ Author page search failed: {e}"
        )

    return None


# ============================================================
# HANDLE IMAGE CROP MODAL
# ============================================================

def handle_image_crop_modal(page):

    print()
    print("Checking image crop modal...")

    try:

        modal = page.locator(
            ".antd-img-crop-modal"
        )

        if modal.count() == 0:
            print("✓ No image crop modal found.")
            return True

        # Wait briefly for modal animation
        time.sleep(1)

        if not modal.first.is_visible():
            print("✓ Crop modal is not visible.")
            return True

        print(
            "⚠️ Image crop modal detected."
        )

        # ----------------------------------------------------
        # Print modal buttons for diagnostics
        # ----------------------------------------------------

        try:

            buttons = modal.first.locator(
                "button"
            )

            button_count = buttons.count()

            print(
                f"Crop modal buttons: {button_count}"
            )

            for i in range(button_count):

                try:

                    txt = buttons.nth(i).inner_text(
                        timeout=2000
                    )

                    cls = buttons.nth(i).get_attribute(
                        "class"
                    )

                    print(
                        f"  Button {i}: "
                        f"text='{txt}' "
                        f"class='{cls}'"
                    )

                except Exception:
                    pass

        except Exception:
            pass

        # ----------------------------------------------------
        # Try positive confirmation buttons
        # ----------------------------------------------------

        positive_names = re.compile(
            r"^(OK|Confirm|Done|Save|Apply|Crop|Upload)$",
            re.IGNORECASE,
        )

        try:

            positive = modal.first.get_by_role(
                "button",
                name=positive_names,
            )

            count = positive.count()

            print(
                f"Positive crop buttons found: {count}"
            )

            for i in range(count):

                try:

                    button = positive.nth(i)

                    if button.is_visible():

                        print(
                            "Clicking crop confirmation "
                            f"button #{i}"
                        )

                        button.click(
                            timeout=10000
                        )

                        time.sleep(2)

                        break

                except Exception as e:

                    print(
                        f"⚠️ Positive button click "
                        f"failed: {e}"
                    )

        except Exception:
            pass

        # ----------------------------------------------------
        # If still open, use Ant Design primary button
        # ----------------------------------------------------

        try:

            if (
                modal.count() > 0
                and modal.first.is_visible()
            ):

                primary = modal.first.locator(
                    "button.ant-btn-primary"
                )

                count = primary.count()

                print(
                    f"Primary buttons in crop modal: "
                    f"{count}"
                )

                for i in range(count):

                    try:

                        button = primary.nth(i)

                        if button.is_visible():

                            print(
                                "Clicking visible "
                                "primary crop button."
                            )

                            button.click(
                                timeout=10000
                            )

                            time.sleep(2)

                            break

                    except Exception as e:

                        print(
                            f"⚠️ Primary button failed: "
                            f"{e}"
                        )

        except Exception:
            pass

        # ----------------------------------------------------
        # Wait for crop modal to disappear
        # ----------------------------------------------------

        try:

            page.locator(
                ".antd-img-crop-modal"
            ).wait_for(
                state="hidden",
                timeout=15000,
            )

            print(
                "✓ Image crop modal closed."
            )

            return True

        except Exception:

            # Check if it completely disappeared
            try:

                if (
                    page.locator(
                        ".antd-img-crop-modal"
                    ).count() == 0
                ):
                    print(
                        "✓ Image crop modal removed."
                    )
                    return True

            except Exception:
                pass

            print(
                "❌ Image crop modal is still open."
            )

            return False

    except Exception as e:

        print(
            f"⚠️ Crop modal handling error: {e}"
        )

        return False


# ============================================================
# WAIT FOR POSSIBLE MODALS
# ============================================================

def close_common_modals(page):

    # Image crop modal is the important one.
    if not handle_image_crop_modal(page):
        return False

    # Sometimes Ant Design modal remains with animation.
    try:

        page.wait_for_timeout(500)

    except Exception:
        pass

    return True


# ============================================================
# VERIFY REAL PUBLIC POST
# ============================================================

def verify(page, candidate_url=None):

    print()
    print("============================================")
    print("VERIFYING PUBLIC SEREY POST")
    print("============================================")

    candidates = []

    if candidate_url:
        candidates.append(candidate_url)

    try:

        current = page.url

        if current:
            candidates.append(current)

    except Exception:
        pass

    # --------------------------------------------------------
    # Check current URL candidates
    # --------------------------------------------------------

    for url in candidates:

        if is_real_serey_post_url(url):

            print(
                f"✓ Verified from browser URL:"
                f"\n  {url}"
            )

            return url

    # --------------------------------------------------------
    # Search page DOM
    # --------------------------------------------------------

    try:

        link = find_post_link(page)

        if link:

            print(
                f"✓ Verified from DOM:"
                f"\n  {link}"
            )

            return link

    except Exception:
        pass

    # --------------------------------------------------------
    # Search HTML
    # --------------------------------------------------------

    try:

        html = page.content()

        url = extract_real_post_url(html)

        if url:

            print(
                f"✓ Verified from page HTML:"
                f"\n  {url}"
            )

            return url

    except Exception:
        pass

    # --------------------------------------------------------
    # Search body text
    # --------------------------------------------------------

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        url = find_url_in_text(
            body_text
        )

        if url:

            print(
                f"✓ Verified from page text:"
                f"\n  {url}"
            )

            return url

    except Exception:
        pass

    print(
        "❌ No real public Serey URL verified."
    )

    return None


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish_post(page, post):

    title = post["title"]
    body = post["body"]

    print()
    print("============================================")
    print("PUBLISHING POST")
    print("============================================")

    print(f"Title: {title}")
    print(f"Steemit: {post['url']}")

    # --------------------------------------------------------
    # Extract image
    # --------------------------------------------------------

    image_url = extract_image(post)

    if image_url:
        print(
            f"Image found: {image_url}"
        )
    else:
        print(
            "No image found."
        )

    image_file = None

    if image_url:
        image_file = download_image(
            image_url
        )

    # --------------------------------------------------------
    # Open New Post page
    # --------------------------------------------------------

    print()
    print(
        f"Opening Serey New Post: {NEW_POST}"
    )

    try:

        page.goto(
            NEW_POST,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    except Exception as e:

        print(
            f"⚠️ Initial page.goto issue: {e}"
        )

    time.sleep(5)

    print(
        f"Current URL: {page.url}"
    )

    # --------------------------------------------------------
    # Login if needed
    # --------------------------------------------------------

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        login_needed = (
            "login" in body_text.lower()
            and "password" in body_text.lower()
        )

    except Exception:
        login_needed = False

    if login_needed:

        print(
            "Login appears to be required."
        )

        # Username
        try:

            user_input = page.locator(
                'input[type="text"], '
                'input[type="email"], '
                'input[name*="user"], '
                'input[name*="login"]'
            ).first

            user_input.fill(
                SEREY_LOGIN,
                timeout=10000,
            )

        except Exception as e:

            print(
                f"⚠️ Username fill failed: {e}"
            )

        # Password
        try:

            password_input = page.locator(
                'input[type="password"]'
            ).first

            password_input.fill(
                SEREY_PASSWORD,
                timeout=10000,
            )

        except Exception as e:

            print(
                f"⚠️ Password fill failed: {e}"
            )

        # Login button
        try:

            login_button = page.get_by_role(
                "button",
                name=re.compile(
                    r"login|sign in",
                    re.IGNORECASE,
                ),
            ).first

            login_button.click(
                timeout=15000
            )

            print(
                "✓ Login button clicked."
            )

            time.sleep(5)

        except Exception as e:

            print(
                f"⚠️ Login click failed: {e}"
            )

    # --------------------------------------------------------
    # Navigate again to New Post
    # --------------------------------------------------------

    try:

        if "/blog/post/new" not in page.url:

            page.goto(
                NEW_POST,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            time.sleep(5)

    except Exception as e:

        print(
            f"⚠️ New Post navigation issue: {e}"
        )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    print("Filling title...")

    try:

        title_input = page.locator(
            'input[placeholder*="title" i], '
            'input[name*="title" i], '
            'textarea[placeholder*="title" i]'
        ).first

        title_input.fill(
            title,
            timeout=15000,
        )

        print(
            "✓ Title filled."
        )

    except Exception as e:

        print(
            f"❌ Title fill failed: {e}"
        )

        return None

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    print("Filling body...")

    body_filled = False

    try:

        editor = page.locator(
            '[contenteditable="true"]'
        ).first

        editor.fill(
            body,
            timeout=15000,
        )

        body_filled = True

        print(
            "✓ Body filled using contenteditable."
        )

    except Exception as e:

        print(
            f"Contenteditable failed: {e}"
        )

    if not body_filled:

        try:

            textarea = page.locator(
                "textarea"
            ).last

            textarea.fill(
                body,
                timeout=15000,
            )

            body_filled = True

            print(
                "✓ Body filled using textarea."
            )

        except Exception as e:

            print(
                f"Textarea body fill failed: {e}"
            )

    if not body_filled:

        print(
            "❌ Could not fill post body."
        )

        return None

    # --------------------------------------------------------
    # IMAGE UPLOAD
    # --------------------------------------------------------

    if image_file and os.path.exists(
        image_file
    ):

        print()
        print(
            "Uploading image..."
        )

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            count = file_inputs.count()

            print(
                f"File inputs found: {count}"
            )

            if count > 0:

                uploaded = False

                for i in range(count):

                    try:

                        file_input = (
                            file_inputs.nth(i)
                        )

                        file_input.set_input_files(
                            image_file,
                            timeout=15000,
                        )

                        uploaded = True

                        print(
                            f"✓ Image uploaded "
                            f"using file input #{i}"
                        )

                        break

                    except Exception as e:

                        print(
                            f"File input #{i} failed: "
                            f"{e}"
                        )

                if not uploaded:

                    print(
                        "⚠️ Could not upload image."
                    )

            else:

                print(
                    "⚠️ No file input found."
                )

        except Exception as e:

            print(
                f"⚠️ Image upload error: {e}"
            )

    # --------------------------------------------------------
    # IMPORTANT:
    # IMAGE CROP MODAL MUST BE CLOSED
    # BEFORE PUBLISH BUTTON
    # --------------------------------------------------------

    print()
    print(
        "Checking upload/crop state..."
    )

    if not close_common_modals(page):

        print(
            "❌ Could not close image crop modal."
        )

        return None

    # --------------------------------------------------------
    # Wait for page to become stable
    # --------------------------------------------------------

    time.sleep(2)

    # --------------------------------------------------------
    # Publish Button
    # --------------------------------------------------------

    print()
    print(
        "Looking for Publish button..."
    )

    try:

        publish_buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"publish",
                re.IGNORECASE,
            ),
        )

        count = publish_buttons.count()

        print(
            f"Publish buttons found: {count}"
        )

        if count == 0:

            print(
                "❌ No Publish button found."
            )

            return None

        # Use first visible publish button
        publish_button = None

        for i in range(count):

            try:

                button = publish_buttons.nth(i)

                if button.is_visible():

                    publish_button = button

                    print(
                        f"Using Publish button #{i}"
                    )

                    break

            except Exception:
                continue

        if publish_button is None:

            print(
                "❌ No visible Publish button."
            )

            return None

        # One more modal check
        if not close_common_modals(page):

            print(
                "❌ Modal still blocking Publish."
            )

            return None

        publish_button.click(
            timeout=20000
        )

        print(
            "✓ First Publish click successful."
        )

    except Exception as e:

        print(
            f"❌ First publish click failed: {e}"
        )

        return None

    # --------------------------------------------------------
    # Wait for possible confirmation modal
    # --------------------------------------------------------

    time.sleep(3)

    print()
    print(
        "Checking for final Publish confirmation..."
    )

    try:

        # Look for visible publish buttons again
        publish_buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"publish",
                re.IGNORECASE,
            ),
        )

        count = publish_buttons.count()

        print(
            f"Publish buttons after first click: {count}"
        )

        clicked_final = False

        for i in range(count):

            try:

                button = publish_buttons.nth(i)

                if not button.is_visible():
                    continue

                # Check if this is inside a modal
                inside_modal = button.locator(
                    "xpath=ancestor::*[contains(@class,'modal')]"
                ).count()

                if inside_modal:

                    print(
                        f"Clicking final Publish "
                        f"button #{i}"
                    )

                    button.click(
                        timeout=15000
                    )

                    clicked_final = True

                    break

            except Exception:
                continue

        if clicked_final:

            print(
                "✓ Final Publish clicked."
            )

        else:

            print(
                "No separate confirmation Publish "
                "button detected."
            )

    except Exception as e:

        print(
            f"⚠️ Final confirmation check: {e}"
        )

    # --------------------------------------------------------
    # Wait for publication
    # --------------------------------------------------------

    print()
    print(
        "Waiting for Serey publication..."
    )

    time.sleep(15)

    # --------------------------------------------------------
    # VERIFY REAL PUBLIC URL
    # --------------------------------------------------------

    real_url = verify(page)

    if real_url:

        print()
        print(
            "============================================"
        )
        print(
            "✓ PUBLICATION VERIFIED"
        )
        print(
            "============================================"
        )
        print(
            f"REAL SEREY URL:\n{real_url}"
        )

        return real_url

    # --------------------------------------------------------
    # If current page isn't post, search author page
    # --------------------------------------------------------

    print()
    print(
        "Direct verification failed."
    )

    print(
        "Trying author page..."
    )

    real_url = search_author_page(
        page
    )

    if real_url:

        print()
        print(
            "============================================"
        )
        print(
            "✓ PUBLICATION VERIFIED THROUGH AUTHOR PAGE"
        )
        print(
            "============================================"
        )
        print(
            real_url
        )

        return real_url

    print()
    print(
        "❌ PUBLICATION VERIFICATION FAILED."
    )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("============================================")
    print("STEEMIT → SEREY AUTO SYNC")
    print("============================================")

    print(
        f"Steemit account: @{STEEM_USERNAME}"
    )

    print(
        f"Serey account: @{SEREY_LOGIN}"
    )

    print(
        f"Posts per run: {POSTS_PER_RUN}"
    )

    print(
        f"Date range: Last {DAYS_TO_CHECK} days"
    )

    print(
        f"Serey site: {SEREY}"
    )

    # --------------------------------------------------------
    # Check credentials
    # --------------------------------------------------------

    if not SEREY_LOGIN:

        print(
            "❌ SEREY_LOGIN is missing."
        )

        return

    if not SEREY_PASSWORD:

        print(
            "❌ SEREY_PASSWORD is missing."
        )

        return

    # --------------------------------------------------------
    # Load synced posts
    # --------------------------------------------------------

    synced = load_synced()

    print()
    print(
        f"Already synced posts: {len(synced)}"
    )

    # --------------------------------------------------------
    # Get last 30 days Steemit posts
    # --------------------------------------------------------

    posts = get_posts()

    if not posts:

        print()
        print(
            "No posts found in the last 30 days."
        )

        return

    # --------------------------------------------------------
    # Find unsynced posts
    # --------------------------------------------------------

    unsynced = []

    for post in posts:

        key = (
            f"{post['author']}/"
            f"{post['permlink']}"
        )

        if key in synced:

            print(
                f"✓ Already synced: {key}"
            )

            continue

        unsynced.append(
            (key, post)
        )

    print()
    print(
        f"Unsynced posts: {len(unsynced)}"
    )

    if not unsynced:

        print(
            "Nothing new to publish."
        )

        return

    # --------------------------------------------------------
    # Only publish POSTS_PER_RUN
    # --------------------------------------------------------

    publishing = unsynced[
        :POSTS_PER_RUN
    ]

    print()
    print(
        f"Publishing this run: "
        f"{len(publishing)}"
    )

    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
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
                "Chrome/120 Safari/537.36"
            ),
        )

        page = context.new_page()

        # ====================================================
        # NETWORK DIAGNOSTICS
        # ====================================================

        def on_request(request):

            try:

                if request.method in [
                    "POST",
                    "PUT",
                    "PATCH",
                ]:

                    print()
                    print(
                        f">>> REQUEST "
                        f"{request.method}"
                    )

                    print(
                        f"URL: {request.url}"
                    )

            except Exception:
                pass

        def on_response(response):

            try:

                status = response.status

                # Only print useful responses
                if (
                    status >= 400
                    or "/api/" in response.url
                    or "/authors/" in response.url
                ):

                    print()
                    print(
                        f"<<< RESPONSE {status}"
                    )

                    print(
                        f"URL: {response.url}"
                    )

                    content_type = (
                        response.headers.get(
                            "content-type",
                            ""
                        )
                    )

                    print(
                        f"Content-Type: "
                        f"{content_type}"
                    )

                    if (
                        "application/json"
                        in content_type
                        or "text"
                        in content_type
                    ):

                        try:

                            text = response.text()

                            print(
                                "Response body preview:"
                            )

                            print(
                                text[:1500]
                            )

                        except Exception:
                            pass

            except Exception:
                pass

        def on_page(page_obj):

            try:

                print()
                print(
                    ">>> NEW PAGE OPENED:"
                )

                print(
                    page_obj.url
                )

            except Exception:
                pass

        def on_navigation(frame):

            try:

                if frame == page.main_frame:

                    print()
                    print(
                        ">>> NAVIGATION:"
                    )

                    print(
                        frame.url
                    )

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        page.on(
            "response",
            on_response
        )

        page.on(
            "popup",
            on_page
        )

        page.on(
            "framenavigated",
            on_navigation
        )

        try:

            # ------------------------------------------------
            # Login / open Serey
            # ------------------------------------------------

            print()
            print(
                "Logging into Serey..."
            )

            page.goto(
                NEW_POST,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            time.sleep(5)

            # ------------------------------------------------
            # If login page exists
            # ------------------------------------------------

            try:

                password_exists = page.locator(
                    'input[type="password"]'
                ).count() > 0

            except Exception:

                password_exists = False

            if password_exists:

                print(
                    "Login form detected."
                )

                try:

                    inputs = page.locator(
                        "input"
                    )

                    input_count = inputs.count()

                    for i in range(input_count):

                        try:

                            inp = inputs.nth(i)

                            input_type = (
                                inp.get_attribute(
                                    "type"
                                )
                                or ""
                            )

                            name = (
                                inp.get_attribute(
                                    "name"
                                )
                                or ""
                            ).lower()

                            placeholder = (
                                inp.get_attribute(
                                    "placeholder"
                                )
                                or ""
                            ).lower()

                            if input_type == "password":

                                inp.fill(
                                    SEREY_PASSWORD,
                                    timeout=10000,
                                )

                            elif (
                                "user" in name
                                or "login" in name
                                or "email" in name
                                or "user" in placeholder
                                or "login" in placeholder
                                or "email" in placeholder
                            ):

                                inp.fill(
                                    SEREY_LOGIN,
                                    timeout=10000,
                                )

                        except Exception:
                            continue

                    login_button = page.get_by_role(
                        "button",
                        name=re.compile(
                            r"login|sign in",
                            re.IGNORECASE,
                        ),
                    ).first

                    login_button.click(
                        timeout=15000
                    )

                    print(
                        "✓ Login clicked."
                    )

                    time.sleep(6)

                except Exception as e:

                    print(
                        f"⚠️ Login process issue: {e}"
                    )

            else:

                print(
                    "Login session appears active."
                )

            # ------------------------------------------------
            # Publish posts
            # ------------------------------------------------

            for key, post in publishing:

                print()
                print(
                    "============================================"
                )

                print(
                    f"Processing: {key}"
                )

                print(
                    f"Title: {post['title']}"
                )

                print(
                    "============================================"
                )

                real_url = publish_post(
                    page,
                    post,
                )

                # IMPORTANT:
                # Only save after real URL verification
                if real_url:

                    synced[key] = {
                        "steemit_url": post["url"],
                        "serey_url": real_url,
                        "title": post["title"],
                        "created": post[
                            "created_string"
                        ],
                        "synced_at": datetime.utcnow().isoformat()
                        + "Z",
                    }

                    save_synced(
                        synced
                    )

                    print()
                    print(
                        "✓ SAVED AS SYNCED"
                    )

                    print(
                        f"Serey URL: {real_url}"
                    )

                else:

                    print()
                    print(
                        "❌ NOT SAVED AS SYNCED"
                    )

                    print(
                        f"Steemit URL: "
                        f"{post['url']}"
                    )

        finally:

            # ------------------------------------------------
            # Cleanup
            # ------------------------------------------------

            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass

            if os.path.exists(
                TEMP_IMAGE
            ):

                try:
                    os.remove(
                        TEMP_IMAGE
                    )
                except Exception:
                    pass

    print()
    print("============================================")
    print("RUN COMPLETE")
    print("============================================")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
