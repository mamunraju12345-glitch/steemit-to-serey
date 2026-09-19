import os
import json
import re
import time
import requests
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"].strip()

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD", ""
).strip()

SEREY = "https://bengali.serey.io"

NEW_POST = f"{SEREY}/write/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "steem_thumbnail.jpg"

POSTS_PER_RUN = 1
DAYS_TO_SYNC = 365


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

            response = requests.post(
                node,
                json=payload,
                timeout=30
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise Exception(data["error"])

            print(
                f"✓ RPC success: {node}",
                flush=True
            )

            return data["result"]

        except Exception as e:

            print(
                f"RPC failed: {e}",
                flush=True
            )

    raise Exception("All Steem RPC nodes failed")


# ============================================================
# DATE
# ============================================================

def parse_steem_date(value):

    if not value:
        return None

    try:

        value = value.strip()

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:

        return None


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

            if isinstance(data, list):
                return set(data)

            if isinstance(data, dict):

                if "synced" in data:
                    return set(data["synced"])

                return set(data.keys())

    except Exception as e:

        print(
            f"Warning: synced file could not be loaded: {e}",
            flush=True
        )

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
# FIRST IMAGE
# ============================================================

def get_first_image(body, metadata):

    # --------------------------------------------------------
    # Markdown image
    # --------------------------------------------------------

    match = re.search(
        r'!\[[^\]]*\]\(\s*(https?://[^)\s]+)',
        body or "",
        re.I
    )

    if match:
        return match.group(1).strip()

    # --------------------------------------------------------
    # HTML image
    # --------------------------------------------------------

    match = re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
        body or "",
        re.I
    )

    if match:
        return match.group(1).strip()

    # --------------------------------------------------------
    # Steem metadata
    # --------------------------------------------------------

    try:

        meta = json.loads(metadata or "{}")

        images = meta.get("image", [])

        if isinstance(images, list):

            for image in images:

                if isinstance(image, str) and image.startswith(
                    "http"
                ):
                    return image

    except Exception:
        pass

    return None


# ============================================================
# CLEAN ARTICLE
# ============================================================

def clean_article(body):

    if not body:
        return ""

    text = body

    # Remove HTML comments
    text = re.sub(
        r'<!--.*?-->',
        '',
        text,
        flags=re.S
    )

    # Remove Markdown images
    text = re.sub(
        r'!\[[^\]]*\]\([^)]*\)',
        '',
        text
    )

    # Remove HTML images
    text = re.sub(
        r'<img\b[^>]*>',
        '',
        text,
        flags=re.I
    )

    # Remove image URLs
    text = re.sub(
        r'https?://[^\s<>"\']+\.(?:jpg|jpeg|png|gif|webp|svg)(?:\?[^\s<>"\']*)?',
        '',
        text,
        flags=re.I
    )

    # HTML links -> visible text
    text = re.sub(
        r'<a\b[^>]*>(.*?)</a>',
        r'\1',
        text,
        flags=re.I | re.S
    )

    # Markdown links -> visible text
    text = re.sub(
        r'\[([^\]]+)\]\([^)]+\)',
        r'\1',
        text
    )

    # Common HTML line breaks
    text = re.sub(
        r'<br\s*/?>',
        '\n',
        text,
        flags=re.I
    )

    # Paragraph/div/center boundaries
    text = re.sub(
        r'</(?:p|div|center|section|article|li|blockquote)>',
        '\n',
        text,
        flags=re.I
    )

    text = re.sub(
        r'<(?:p|div|center|section|article|li|blockquote)[^>]*>',
        '',
        text,
        flags=re.I
    )

    # Remove remaining HTML tags
    text = re.sub(
        r'<[^>]+>',
        '',
        text
    )

    # Markdown headings
    text = re.sub(
        r'^\s{0,3}#{1,6}\s*',
        '',
        text,
        flags=re.M
    )

    # Bold / italic / strike
    text = re.sub(
        r'(\*\*|__)(.*?)\1',
        r'\2',
        text,
        flags=re.S
    )

    text = re.sub(
        r'(\*|_)(.*?)\1',
        r'\2',
        text,
        flags=re.S
    )

    text = re.sub(
        r'~~(.*?)~~',
        r'\1',
        text,
        flags=re.S
    )

    # Horizontal rules
    text = re.sub(
        r'^\s*([-*_])(?:\s*\1){2,}\s*$',
        '',
        text,
        flags=re.M
    )

    # Decode common HTML entities
    text = (
        text
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )

    # Remove excessive blank lines
    text = re.sub(
        r'\n[ \t]+\n',
        '\n\n',
        text
    )

    text = re.sub(
        r'\n{3,}',
        '\n\n',
        text
    )

    # Remove spaces at line ends
    text = re.sub(
        r'[ \t]+\n',
        '\n',
        text
    )

    return text.strip()


# ============================================================
# CLEAN POST
# ============================================================

def prepare_post(post):

    body = post.get("body", "")
    metadata = post.get("json_metadata", "{}")

    image = get_first_image(
        body,
        metadata
    )

    clean_body = clean_article(body)

    return {
        "id": f"{post.get('author')}/{post.get('permlink')}",
        "title": post.get("title", "").strip(),
        "body": clean_body,
        "image": image,
        "category": post.get("category", ""),
        "created": post.get("created", "")
    }


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

    cutoff = datetime.now(
        timezone.utc
    ).timestamp() - (
        DAYS_TO_SYNC * 24 * 60 * 60
    )

    page_number = 0

    while len(posts) < 5000:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:

            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        page_number += 1

        print(
            f"Steem page {page_number}: requesting 100 results",
            flush=True
        )

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        print(
            f"Steem page {page_number}: {len(result)} results",
            flush=True
        )

        batch = result[1:] if start_author else result

        if not batch:
            break

        for post in batch:

            author = post.get(
                "author",
                ""
            )

            permlink = post.get(
                "permlink",
                ""
            )

            if author != STEEM_USERNAME:
                continue

            if not permlink:
                continue

            post_id = f"{author}/{permlink}"

            if post_id in seen:
                continue

            seen.add(post_id)

            created = parse_steem_date(
                post.get("created", "")
            )

            if not created:
                continue

            if created.timestamp() < cutoff:
                continue

            posts.append(
                prepare_post(post)
            )

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

    # Oldest -> newest
    posts.sort(
        key=lambda x: parse_steem_date(
            x.get("created", "")
        ) or datetime.min.replace(
            tzinfo=timezone.utc
        )
    )

    print(
        f"Total posts in last {DAYS_TO_SYNC} days: {len(posts)}",
        flush=True
    )

    if posts:

        print(
            f"Oldest: {posts[0]['created']} {posts[0]['id']}",
            flush=True
        )

        print(
            f"Newest: {posts[-1]['created']} {posts[-1]['id']}",
            flush=True
        )

    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    if not url:
        return None

    try:

        print(
            "Downloading thumbnail:",
            flush=True
        )

        print(
            url,
            flush=True
        )

        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "content-type",
            ""
        ).lower()

        if "image" not in content_type:

            print(
                f"Not an image: {content_type}",
                flush=True
            )

            return None

        if len(response.content) > 30 * 1024 * 1024:

            print(
                "Image is larger than 30 MB.",
                flush=True
            )

            return None

        with open(
            TEMP_IMAGE,
            "wb"
        ) as f:

            f.write(response.content)

        print(
            f"✓ Thumbnail downloaded: {TEMP_IMAGE} "
            f"({len(response.content)} bytes)",
            flush=True
        )

        return TEMP_IMAGE

    except Exception as e:

        print(
            f"Thumbnail download failed: {e}",
            flush=True
        )

        return None


# ============================================================
# CROP MODAL
# ============================================================

def handle_crop_modal(page):

    print(
        "Checking thumbnail crop modal...",
        flush=True
    )

    try:

        # Wait a short time for modal
        page.wait_for_timeout(1500)

        crop = page.locator(
            '[data-testid="cropper"]'
        )

        modal = page.locator(
            '.ant-modal'
        )

        if crop.count() == 0 and modal.count() == 0:

            print(
                "No crop modal detected.",
                flush=True
            )

            return True

        print(
            "✓ Image crop modal detected",
            flush=True
        )

        # ----------------------------------------------------
        # Find visible modal
        # ----------------------------------------------------

        visible_modal = None

        for i in range(modal.count()):

            m = modal.nth(i)

            try:

                if m.is_visible():
                    visible_modal = m
                    break

            except Exception:
                pass

        if visible_modal:

            buttons = visible_modal.locator(
                "button"
            )

        else:

            buttons = page.locator(
                ".ant-modal button"
            )

        print(
            f"Modal buttons found: {buttons.count()}",
            flush=True
        )

        # ----------------------------------------------------
        # Print buttons
        # ----------------------------------------------------

        for i in range(buttons.count()):

            b = buttons.nth(i)

            try:

                text = b.inner_text().strip()
            except Exception:
                text = ""

            try:

                aria = b.get_attribute("aria-label") or ""
            except Exception:
                aria = ""

            try:

                title = b.get_attribute("title") or ""
            except Exception:
                title = ""

            print(
                f"Modal button {i}: "
                f"text='{text}' "
                f"aria='{aria}' "
                f"title='{title}'",
                flush=True
            )

        # ----------------------------------------------------
        # Confirmation words
        # ----------------------------------------------------

        confirmation_words = [
            "OK",
            "Ok",
            "ok",
            "Confirm",
            "CONFIRM",
            "Save",
            "SAVE",
            "Done",
            "DONE",
            "Upload",
            "UPLOAD",
            "Crop",
            "CROP",
            "Continue",
            "CONTINUE"
        ]

        for i in range(buttons.count()):

            b = buttons.nth(i)

            try:

                if not b.is_visible():
                    continue

                text = b.inner_text().strip()
                aria = (
                    b.get_attribute("aria-label")
                    or ""
                ).strip()

                title = (
                    b.get_attribute("title")
                    or ""
                ).strip()

                combined = (
                    f"{text} {aria} {title}"
                ).strip()

                for word in confirmation_words:

                    if combined.lower() == word.lower():

                        print(
                            f"✓ Clicking crop confirmation "
                            f"button: {combined}",
                            flush=True
                        )

                        b.click(
                            force=True,
                            timeout=10000
                        )

                        page.wait_for_timeout(2000)

                        # Verify modal disappeared
                        if (
                            page.locator(
                                '[data-testid="cropper"]'
                            ).count() == 0
                        ):

                            print(
                                "✓ Crop modal closed",
                                flush=True
                            )

                            return True

            except Exception:
                continue

        # ----------------------------------------------------
        # Fallback: exact text
        # ----------------------------------------------------

        for word in [
            "OK",
            "Confirm",
            "Save",
            "Done",
            "Upload",
            "Crop"
        ]:

            try:

                loc = page.get_by_text(
                    word,
                    exact=True
                )

                for i in range(loc.count()):

                    item = loc.nth(i)

                    if item.is_visible():

                        print(
                            f"✓ Clicking crop text: {word}",
                            flush=True
                        )

                        item.click(
                            force=True,
                            timeout=10000
                        )

                        page.wait_for_timeout(2000)

                        if page.locator(
                            '[data-testid="cropper"]'
                        ).count() == 0:

                            print(
                                "✓ Crop modal closed",
                                flush=True
                            )

                            return True

            except Exception:
                pass

        # ----------------------------------------------------
        # Keyboard fallback
        # ----------------------------------------------------

        try:

            print(
                "Trying Enter key for crop confirmation...",
                flush=True
            )

            page.keyboard.press("Enter")

            page.wait_for_timeout(2000)

            if page.locator(
                '[data-testid="cropper"]'
            ).count() == 0:

                print(
                    "✓ Crop modal closed with Enter",
                    flush=True
                )

                return True

        except Exception:
            pass

        print(
            "❌ Crop modal could not be closed.",
            flush=True
        )

        return False

    except Exception as e:

        print(
            f"Crop modal check failed: {e}",
            flush=True
        )

        return False


# ============================================================
# FILL TITLE
# ============================================================

def fill_title(page, title):

    print(
        "Looking for Serey title field...",
        flush=True
    )

    selectors = [
        'textarea[placeholder="Enter title..."]',
        'input[placeholder="Enter title..."]',
        'textarea[name="title"]',
        'input[name="title"]',
        'input[placeholder*="Title" i]',
        'textarea[placeholder*="Title" i]'
    ]

    for selector in selectors:

        try:

            loc = page.locator(selector)

            print(
                f"Checking: {selector} -> {loc.count()}",
                flush=True
            )

            for i in range(loc.count()):

                field = loc.nth(i)

                if field.is_visible():

                    field.fill(title)

                    print(
                        f"✓ Title field found: {selector}",
                        flush=True
                    )

                    print(
                        "✓ Title filled",
                        flush=True
                    )

                    return True

        except Exception:
            continue

    print(
        "❌ Title field not found.",
        flush=True
    )

    return False


# ============================================================
# FILL ARTICLE
# ============================================================

def fill_article(page, body):

    print(
        "Looking for content editor...",
        flush=True
    )

    editors = page.locator(
        '[contenteditable="true"]'
    )

    for i in range(editors.count()):

        editor = editors.nth(i)

        try:

            if not editor.is_visible():
                continue

            print(
                "✓ Editor found: [contenteditable=\"true\"]",
                flush=True
            )

            try:

                editor.click(
                    timeout=5000
                )

            except Exception:

                print(
                    "Normal editor click failed.",
                    flush=True
                )

                print(
                    "Using force click...",
                    flush=True
                )

                editor.click(
                    force=True
                )

            # Use keyboard insertion rather than relying
            # on contenteditable.fill() compatibility.

            try:

                editor.fill(body)

            except Exception:

                page.keyboard.insert_text(body)

            print(
                f"✓ Clean article inserted "
                f"({len(body)} characters)",
                flush=True
            )

            return True

        except Exception as e:

            print(
                f"Editor attempt failed: {e}",
                flush=True
            )

    print(
        "❌ Content editor not found.",
        flush=True
    )

    return False


# ============================================================
# THUMBNAIL
# ============================================================

def upload_thumbnail(page, image):

    if not image:
        print(
            "No thumbnail available.",
            flush=True
        )
        return True

    print()
    print("=" * 60)
    print(
        "Uploading FIRST IMAGE as thumbnail"
    )
    print("=" * 60)

    print(
        f"Thumbnail file: {image}",
        flush=True
    )

    # --------------------------------------------------------
    # File inputs
    # --------------------------------------------------------

    inputs = page.locator(
        'input[type="file"]'
    )

    print(
        f"File inputs detected: {inputs.count()}",
        flush=True
    )

    for i in range(inputs.count()):

        try:

            inp = inputs.nth(i)

            print(
                f"File input {i}: "
                f"accept={inp.get_attribute('accept')} "
                f"name={inp.get_attribute('name')}",
                flush=True
            )

        except Exception:
            pass

    if inputs.count() == 0:

        print(
            "❌ No file input found.",
            flush=True
        )

        return False

    # Serey currently exposes one image input.
    # That input is used for thumbnail.

    try:

        inputs.first.set_input_files(
            image
        )

        print(
            "✓ Thumbnail uploaded using single image input",
            flush=True
        )

    except Exception as e:

        print(
            f"❌ Thumbnail upload failed: {e}",
            flush=True
        )

        return False

    # --------------------------------------------------------
    # IMPORTANT: crop modal
    # --------------------------------------------------------

    if not handle_crop_modal(page):

        print(
            "❌ Thumbnail crop confirmation failed.",
            flush=True
        )

        return False

    print(
        "✓ Thumbnail crop confirmed",
        flush=True
    )

    return True


# ============================================================
# CATEGORY
# ============================================================

def select_category(page, steem_category):

    if not steem_category:
        return False

    print(
        f"Steem category: {steem_category}",
        flush=True
    )

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        if "Your post belongs to category:" in body_text:

            print(
                "Serey suggested category automatically.",
                flush=True
            )

    except Exception:
        pass

    selectors = [
        "text=Select category",
        "text=Select Category"
    ]

    for selector in selectors:

        try:

            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            for i in range(loc.count()):

                item = loc.nth(i)

                if not item.is_visible():
                    continue

                item.click(
                    force=True
                )

                page.wait_for_timeout(800)

                # Exact category
                exact = page.get_by_text(
                    steem_category,
                    exact=True
                )

                for j in range(exact.count()):

                    option = exact.nth(j)

                    if option.is_visible():

                        option.click(
                            force=True
                        )

                        print(
                            f"✓ Category selected: "
                            f"{steem_category}",
                            flush=True
                        )

                        return True

                # role=option fallback
                options = page.locator(
                    '[role="option"]'
                )

                for j in range(options.count()):

                    option = options.nth(j)

                    try:

                        if not option.is_visible():
                            continue

                        txt = option.inner_text().strip()

                        if txt.lower() == steem_category.lower():

                            option.click(
                                force=True
                            )

                            print(
                                f"✓ Category selected: {txt}",
                                flush=True
                            )

                            return True

                    except Exception:
                        continue

        except Exception:
            continue

    print(
        "Category selection skipped.",
        flush=True
    )

    return False


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(page):

    try:

        selectors = [
            "text=Select sub category",
            "text=Select Sub Category",
            "text=Select sub-category",
            "text=Select Sub-category"
        ]

        for selector in selectors:

            loc = page.locator(selector)

            if loc.count() == 0:
                continue

            for i in range(loc.count()):

                item = loc.nth(i)

                if not item.is_visible():
                    continue

                item.click(
                    force=True
                )

                page.wait_for_timeout(800)

                options = page.locator(
                    '[role="option"]'
                )

                for j in range(options.count()):

                    option = options.nth(j)

                    if option.is_visible():

                        option.click(
                            force=True
                        )

                        print(
                            "✓ Sub Category selected.",
                            flush=True
                        )

                        return True

        print(
            "No Sub Category available.",
            flush=True
        )

    except Exception as e:

        print(
            f"Sub Category skipped: {e}",
            flush=True
        )

    return False


# ============================================================
# DEBUG PAGE
# ============================================================

def save_debug(page):

    try:

        with open(
            "serey_publish_debug.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                page.content()
            )

        page.screenshot(
            path="serey_publish_debug.png",
            full_page=True
        )

        print(
            "✓ Serey debug HTML and screenshot saved.",
            flush=True
        )

    except Exception as e:

        print(
            f"Debug save failed: {e}",
            flush=True
        )


# ============================================================
# FIND PUBLISH BUTTON
# ============================================================

def find_publish_button(page):

    # --------------------------------------------------------
    # First: buttons
    # --------------------------------------------------------

    buttons = page.locator(
        "button"
    )

    print(
        f"Publish search: {buttons.count()} buttons detected",
        flush=True
    )

    for i in range(buttons.count()):

        button = buttons.nth(i)

        try:

            if not button.is_visible():
                continue

            text = button.inner_text().strip()

            aria = (
                button.get_attribute("aria-label")
                or ""
            ).strip()

            title = (
                button.get_attribute("title")
                or ""
            ).strip()

            data_testid = (
                button.get_attribute("data-testid")
                or ""
            ).strip()

            print(
                f"Button {i}: "
                f"text='{text}' "
                f"aria='{aria}' "
                f"title='{title}' "
                f"testid='{data_testid}'",
                flush=True
            )

        except Exception:
            continue

    # --------------------------------------------------------
    # Exact button text
    # --------------------------------------------------------

    candidates = [
        page.get_by_role(
            "button",
            name=re.compile(
                r"^\s*Publish\s*$",
                re.I
            )
        ),
        page.get_by_text(
            "Publish",
            exact=True
        )
    ]

    for locator in candidates:

        try:

            for i in range(locator.count()):

                item = locator.nth(i)

                if item.is_visible():

                    print(
                        "✓ Publish button found by text/role.",
                        flush=True
                    )

                    return item

        except Exception:
            continue

    # --------------------------------------------------------
    # Button attributes
    # --------------------------------------------------------

    attribute_selectors = [
        'button[aria-label*="publish" i]',
        'button[title*="publish" i]',
        'button[data-testid*="publish" i]',
        '[role="button"][aria-label*="publish" i]',
        '[role="button"][title*="publish" i]'
    ]

    for selector in attribute_selectors:

        try:

            loc = page.locator(selector)

            for i in range(loc.count()):

                item = loc.nth(i)

                if item.is_visible():

                    print(
                        f"✓ Publish button found: {selector}",
                        flush=True
                    )

                    return item

        except Exception:
            continue

    # --------------------------------------------------------
    # Search any visible element containing Publish
    # --------------------------------------------------------

    try:

        elements = page.locator(
            "button, [role='button'], a"
        )

        for i in range(elements.count()):

            item = elements.nth(i)

            if not item.is_visible():
                continue

            try:
                txt = item.inner_text().strip()
            except Exception:
                txt = ""

            if re.fullmatch(
                r"publish",
                txt,
                re.I
            ):

                print(
                    "✓ Publish button found by DOM fallback.",
                    flush=True
                )

                return item

    except Exception:
        pass

    return None


# ============================================================
# VERIFY PUBLISHED URL
# ============================================================

def is_published_post_url(url):

    try:

        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .split(":")[0]
        )

        allowed_hosts = {
            "serey.io",
            "www.serey.io",
            "bengali.serey.io"
        }

        if host not in allowed_hosts:
            return False

        parts = [
            x for x in parsed.path.split("/")
            if x
        ]

        if len(parts) < 3:
            return False

        if parts[0].lower() != "authors":
            return False

        if not parts[1] or not parts[2]:
            return False

        return True

    except Exception:

        return False


# ============================================================
# VERIFY PUBLICATION
# ============================================================

def verify_published_page(page, expected_title):

    print()
    print("=" * 60)
    print(
        "VERIFYING PUBLISHED POST..."
    )
    print("=" * 60)

    for attempt in range(6):

        page.wait_for_timeout(5000)

        url = page.url

        print(
            f"Verification attempt {attempt + 1}:",
            flush=True
        )

        print(
            f"Current URL: {url}",
            flush=True
        )

        if is_published_post_url(url):

            print(
                "✓ PUBLISHED AUTHOR URL FOUND!",
                flush=True
            )

            # Reload to ensure it is actually accessible
            try:

                page.reload(
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                page.wait_for_timeout(3000)

            except Exception as e:

                print(
                    f"Reload warning: {e}",
                    flush=True
                )

            try:

                visible_text = page.locator(
                    "body"
                ).inner_text(
                    timeout=10000
                )

                if visible_text.strip():

                    print(
                        "✓ Published page contains visible content.",
                        flush=True
                    )

                    if expected_title.lower() in visible_text.lower():

                        print(
                            "✓ Published title confirmed.",
                            flush=True
                        )

                    else:

                        print(
                            "⚠ Title not directly found, "
                            "but published URL is valid.",
                            flush=True
                        )

                    print(
                        f"✓ VERIFIED URL: {page.url}",
                        flush=True
                    )

                    return True, page.url

            except Exception as e:

                print(
                    f"Published page content check failed: {e}",
                    flush=True
                )

                # URL itself is still valid
                return True, url

    print(
        "❌ Publication could not be verified.",
        flush=True
    )

    return False, None


# ============================================================
# PUBLISH POST
# ============================================================

def publish_post(page, post):

    print()
    print("=" * 60)
    print(
        "Starting sync:"
    )
    print(
        post["id"]
    )
    print("=" * 60)

    print(
        f"Title: {post['title']}",
        flush=True
    )

    print(
        f"Created: {post['created']}",
        flush=True
    )

    print(
        f"Original/clean body length: "
        f"{len(post['body'])}",
        flush=True
    )

    print(
        f"First image: {post.get('image')}",
        flush=True
    )

    # --------------------------------------------------------
    # OPEN WRITE PAGE
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    print(
        f"Write page: {NEW_POST}",
        flush=True
    )

    print(
        f"Current write URL: {page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    if not fill_title(
        page,
        post["title"]
    ):

        save_debug(page)

        raise Exception(
            "Serey title field not found."
        )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    if not fill_article(
        page,
        post["body"]
    ):

        save_debug(page)

        raise Exception(
            "Serey article editor not found."
        )

    # --------------------------------------------------------
    # THUMBNAIL
    # --------------------------------------------------------

    image = download_image(
        post.get("image")
    )

    if image:

        if not upload_thumbnail(
            page,
            image
        ):

            save_debug(page)

            raise Exception(
                "Thumbnail upload/crop failed."
            )

    # --------------------------------------------------------
    # IMPORTANT:
    # After thumbnail crop, make sure modal is gone.
    # --------------------------------------------------------

    if page.locator(
        '[data-testid="cropper"]'
    ).count() > 0:

        print(
            "Cropper still exists. Trying again...",
            flush=True
        )

        if not handle_crop_modal(page):

            save_debug(page)

            raise Exception(
                "Crop modal is still open."
            )

    print(
        "✓ Ready to continue after thumbnail.",
        flush=True
    )

    # --------------------------------------------------------
    # FIRST PUBLISH / CONTINUE
    # --------------------------------------------------------

    print()
    print(
        "Searching for FIRST Publish / Continue button...",
        flush=True
    )

    first_publish = find_publish_button(page)

    if not first_publish:

        print(
            "No Publish button at first stage.",
            flush=True
        )

        save_debug(page)

        # Sometimes Serey exposes another Continue/Next
        continue_candidates = [
            page.get_by_role(
                "button",
                name=re.compile(
                    r"^\s*(Continue|Next|Submit)\s*$",
                    re.I
                )
            ),
            page.get_by_text(
                "Continue",
                exact=True
            ),
            page.get_by_text(
                "Next",
                exact=True
            )
        ]

        for locator in continue_candidates:

            try:

                for i in range(locator.count()):

                    item = locator.nth(i)

                    if item.is_visible():

                        print(
                            "✓ Continue/Next button found.",
                            flush=True
                        )

                        item.click(
                            force=True
                        )

                        page.wait_for_timeout(3000)

                        first_publish = find_publish_button(
                            page
                        )

                        break

            except Exception:
                continue

            if first_publish:
                break

    if first_publish:

        try:

            print(
                "✓ Clicking first Publish button...",
                flush=True
            )

            first_publish.click(
                force=True,
                timeout=15000
            )

            print(
                "✓ FIRST PUBLISH CLICKED",
                flush=True
            )

            page.wait_for_timeout(3000)

        except Exception as e:

            print(
                f"First Publish click failed: {e}",
                flush=True
            )

    else:

        print(
            "No first-stage Publish/Continue found.",
            flush=True
        )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    select_category(
        page,
        post.get("category", "")
    )

    # --------------------------------------------------------
    # SUB CATEGORY
    # --------------------------------------------------------

    select_subcategory(
        page
    )

    # --------------------------------------------------------
    # FINAL PUBLISH
    # --------------------------------------------------------

    print()
    print(
        "=" * 60
    )
    print(
        "Searching for FINAL Publish..."
    )
    print(
        "=" * 60
    )

    page.wait_for_timeout(1500)

    final_button = find_publish_button(
        page
    )

    if not final_button:

        print(
            "❌ FINAL Publish button not found.",
            flush=True
        )

        save_debug(page)

        return False, None

    try:

        print(
            "✓ FINAL Publish button found.",
            flush=True
        )

        final_button.click(
            force=True,
            timeout=15000
        )

        print(
            "✓ FINAL PUBLISH CLICKED",
            flush=True
        )

    except Exception as e:

        print(
            f"Final Publish click failed: {e}",
            flush=True
        )

        save_debug(page)

        return False, None

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    success, published_url = verify_published_page(
        page,
        post["title"]
    )

    if success:

        print()
        print(
            "✓✓✓ POST SUCCESSFULLY PUBLISHED ✓✓✓",
            flush=True
        )

        print(
            f"Published URL: {published_url}",
            flush=True
        )

        return True, published_url

    print(
        "❌ Publication verification failed.",
        flush=True
    )

    save_debug(page)

    return False, None


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

    page.wait_for_timeout(3000)

    # Already logged in
    if "/login" not in page.url.lower():

        try:

            text = page.locator(
                "body"
            ).inner_text()

            if (
                "Log in" not in text
                or "Logout" in text
                or "Log out" in text
            ):

                print(
                    f"After login URL: {page.url}",
                    flush=True
                )

        except Exception:
            pass

    # Login button
    login_buttons = page.locator(
        'a:has-text("Log in"),'
        'button:has-text("Log in"),'
        'a:has-text("Log In"),'
        'button:has-text("Log In")'
    )

    if login_buttons.count() == 0:

        print(
            f"After login URL: {page.url}",
            flush=True
        )

        print(
            "✓ LOGGED INTO SEREY SUCCESSFULLY!",
            flush=True
        )

        return True

    try:

        login_buttons.first.click(
            force=True
        )

        page.wait_for_timeout(2500)

    except Exception:

        # Maybe already on a login page
        pass

    # Username
    username = page.locator(
        'input[placeholder*="Username" i]'
    ).first

    if username.count() == 0:

        raise Exception(
            "Serey Username field not found."
        )

    username.fill(
        SEREY_LOGIN
    )

    # Private key/password
    password = page.locator(
        'input[placeholder*="Private Key" i],'
        'input[type="password"]'
    ).first

    if password.count() == 0:

        raise Exception(
            "Serey password/private key field not found."
        )

    password.fill(
        SEREY_PASSWORD
    )

    # Login submit
    submit = page.locator(
        'button:has-text("Log in"),'
        'button:has-text("Log In"),'
        'button[type="submit"]'
    )

    if submit.count() == 0:

        raise Exception(
            "Serey login button not found."
        )

    submit.last.click(
        force=True
    )

    page.wait_for_timeout(6000)

    print(
        f"After login URL: {page.url}",
        flush=True
    )

    if "/login" in page.url.lower():

        raise Exception(
            "Serey login failed."
        )

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print(
        "STEEM -> SEREY AUTO SYNC"
    )
    print("=" * 60)

    print(
        f"• First image = thumbnail"
    )

    print(
        f"• Thumbnail crop = automatic"
    )

    print(
        f"• Body images = removed"
    )

    print(
        f"• Steem HTML/Markdown = cleaned"
    )

    print(
        f"• Posts per run = {POSTS_PER_RUN}"
    )

    print(
        f"• Sync period = {DAYS_TO_SYNC} days"
    )

    print(
        f"• Published URL = REQUIRED"
    )

    print(
        f"• Date handling = UTC SAFE"
    )

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

    posts_to_run = new_posts[
        :POSTS_PER_RUN
    ]

    print(
        f"Posts selected this run: "
        f"{len(posts_to_run)}",
        flush=True
    )

    if not posts_to_run:

        print(
            "Nothing to publish.",
            flush=True
        )

        return

    for post in posts_to_run:

        print()
        print(
            f"Selected: {post['id']}",
            flush=True
        )

        print(
            f"Created: {post['created']}",
            flush=True
        )

        print(
            f"Title: {post['title']}",
            flush=True
        )

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
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

                    success, published_url = publish_post(
                        page,
                        post
                    )

                    if success and published_url:

                        # ONLY NOW mark as synced
                        synced.add(
                            post["id"]
                        )

                        save_synced(
                            synced
                        )

                        print()
                        print(
                            "=" * 60
                        )

                        print(
                            f"✓ SAVED AS SYNCED: "
                            f"{post['id']}"
                        )

                        print(
                            f"✓ Published URL: "
                            f"{published_url}"
                        )

                        print(
                            "=" * 60
                        )

                    else:

                        print()
                        print(
                            f"⚠ FAILED: "
                            f"{post['id']}"
                        )

                        print(
                            "⚠ This post will NOT be "
                            "added to synced_posts.json."
                        )

                except Exception as e:

                    print()
                    print(
                        f"✗ FAILED TO SYNC: "
                        f"{post['id']}"
                    )

                    print(
                        f"Reason: {e}"
                    )

                    print(
                        "⚠ This post will NOT be "
                        "added to synced_posts.json."
                    )

        finally:

            if os.path.exists(
                TEMP_IMAGE
            ):

                try:

                    os.remove(
                        TEMP_IMAGE
                    )

                    print(
                        "Removed temporary thumbnail.",
                        flush=True
                    )

                except Exception:
                    pass

            browser.close()

    print()
    print("=" * 60)
    print(
        "RUN FINISHED"
    )
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
