import os
import re
import json
import time
import requests

from datetime import datetime, timedelta, timezone
from pathlib import Path

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
DAYS_TO_SYNC = 365

IMAGE_PREFIX = "steem_image_"

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://api.steem.fans",
]

REQUEST_TIMEOUT = 30
MAX_IMAGE_SIZE = 30 * 1024 * 1024


# ============================================================
# STEEM RPC
# ============================================================

def steem_rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    last_error = None

    for node in STEEM_NODES:

        try:

            print(f"RPC: {node}")

            response = requests.post(
                node,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise RuntimeError(str(data["error"]))

            print(f"✓ RPC success: {node}")

            return data["result"]

        except Exception as e:

            last_error = e

            print(f"✗ RPC failed: {node}")
            print(f"  Reason: {e}")

    raise RuntimeError(
        f"All Steem RPC nodes failed. "
        f"Last error: {last_error}"
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

        if isinstance(data, list):
            return set(data)

        if isinstance(data, dict):
            return set(data.keys())

    except Exception as e:

        print(
            f"Warning: Could not read "
            f"{SYNC_FILE}: {e}"
        )

    return set()


def save_synced(synced):

    with open(
        SYNC_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(list(synced)),
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# EXTRACT BODY IMAGES
# ============================================================

def extract_body_images(body):

    images = []

    markdown_pattern = re.compile(
        r'!\[[^\]]*\]\(\s*(https?://[^)\s]+)',
        re.IGNORECASE
    )

    html_pattern = re.compile(
        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
        re.IGNORECASE
    )

    for url in markdown_pattern.findall(body):

        if url not in images:
            images.append(url)

    for url in html_pattern.findall(body):

        if url not in images:
            images.append(url)

    return images


# ============================================================
# EXTRACT METADATA IMAGES
# ============================================================

def extract_metadata_images(post):

    images = []

    try:

        metadata = post.get(
            "json_metadata",
            ""
        )

        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        if isinstance(metadata, dict):

            meta_images = metadata.get(
                "image",
                []
            )

            if isinstance(meta_images, str):
                meta_images = [meta_images]

            if isinstance(meta_images, list):

                for url in meta_images:

                    if (
                        isinstance(url, str)
                        and url.startswith("http")
                        and url not in images
                    ):
                        images.append(url)

    except Exception:
        pass

    return images


# ============================================================
# BODY IMAGE PARSER
# ============================================================

IMAGE_RE = re.compile(
    r'!\[[^\]]*\]\(\s*(https?://[^)\s]+)\s*\)'
    r'|'
    r'<img[^>]+src=["\'](https?://[^"\']+)["\'][^>]*>',
    re.IGNORECASE
)


def split_body_with_images(body):

    parts = []

    last = 0

    for match in IMAGE_RE.finditer(body):

        text_part = body[
            last:match.start()
        ]

        if text_part:
            parts.append(
                ("text", text_part)
            )

        image_url = (
            match.group(1)
            or match.group(2)
        )

        parts.append(
            ("image", image_url)
        )

        last = match.end()

    remaining = body[last:]

    if remaining:
        parts.append(
            ("text", remaining)
        )

    return parts


# ============================================================
# CLEAN BODY
# ============================================================

def clean_post(body):

    if not body:
        return ""

    body = re.sub(
        r"\n{4,}",
        "\n\n\n",
        body
    )

    return body.strip()


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    now = datetime.now(timezone.utc)

    cutoff = (
        now -
        timedelta(days=DAYS_TO_SYNC)
    )

    posts = []
    seen_ids = set()

    start_author = STEEM_USERNAME
    start_permlink = ""

    page_number = 0

    while True:

        page_number += 1

        try:

            batch = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                [
                    {
                        "tag": STEEM_USERNAME,
                        "limit": 100,
                        "start_author": start_author,
                        "start_permlink": start_permlink,
                    }
                ]
            )

        except Exception as e:

            print(
                f"Failed to get Steem page "
                f"{page_number}: {e}"
            )

            break

        if not batch:
            break

        print(
            f"Steem page {page_number}: "
            f"{len(batch)} results"
        )

        reached_cutoff = False

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

            post_id = (
                f"{author}/{permlink}"
            )

            if post_id in seen_ids:
                continue

            seen_ids.add(post_id)

            created = post.get(
                "created"
            )

            if not created:
                continue

            try:

                created_dt = datetime.fromisoformat(
                    created.replace(
                        "Z",
                        "+00:00"
                    )
                )

                if created_dt.tzinfo is None:

                    created_dt = created_dt.replace(
                        tzinfo=timezone.utc
                    )

                created_dt = created_dt.astimezone(
                    timezone.utc
                )

            except Exception:
                continue

            if created_dt < cutoff:

                reached_cutoff = True
                continue

            posts.append({
                "id": post_id,
                "author": author,
                "permlink": permlink,
                "title": post.get(
                    "title",
                    ""
                ),
                "body": post.get(
                    "body",
                    ""
                ),
                "created": created_dt.isoformat(),
                "created_dt": created_dt,
                "json_metadata": post.get(
                    "json_metadata",
                    ""
                )
            })

        last = batch[-1]

        last_author = last.get(
            "author",
            ""
        )

        last_permlink = last.get(
            "permlink",
            ""
        )

        if (
            start_author == last_author
            and
            start_permlink == last_permlink
        ):
            break

        start_author = last_author
        start_permlink = last_permlink

        if reached_cutoff:
            break

        if len(batch) < 100:
            break

    posts.sort(
        key=lambda x: x["created_dt"]
    )

    return posts


# ============================================================
# IMAGE EXTENSION
# ============================================================

def detect_extension(
    url,
    content_type,
    data
):

    content_type = (
        content_type or ""
    ).lower()

    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"

    if "png" in content_type:
        return ".png"

    if "webp" in content_type:
        return ".webp"

    if "gif" in content_type:
        return ".gif"

    if "svg" in content_type:
        return ".svg"

    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"

    if data.startswith(b"\x89PNG"):
        return ".png"

    if (
        data.startswith(b"RIFF")
        and
        b"WEBP" in data[:16]
    ):
        return ".webp"

    if data.startswith(b"GIF8"):
        return ".gif"

    url_path = (
        url.lower()
        .split("?")[0]
    )

    for ext in [
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".svg"
    ]:

        if url_path.endswith(ext):
            return ext

    return ".jpg"


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(
    url,
    index
):

    print()
    print("Downloading image:")
    print(url)

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/153 Safari/537.36"
            )
        }
    )

    response.raise_for_status()

    data = response.content

    if not data:
        raise RuntimeError(
            "Downloaded image is empty."
        )

    if len(data) > MAX_IMAGE_SIZE:
        raise RuntimeError(
            "Image is larger than "
            f"{MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )

    extension = detect_extension(
        url,
        response.headers.get(
            "content-type",
            ""
        ),
        data
    )

    filename = (
        f"{IMAGE_PREFIX}"
        f"{index}"
        f"{extension}"
    )

    path = Path(filename)

    path.write_bytes(data)

    print(
        f"✓ Image downloaded: "
        f"{filename} "
        f"({len(data)} bytes)"
    )

    return str(path)


# ============================================================
# DOWNLOAD ALL BODY IMAGES
# ============================================================

def download_body_images(body_images):

    downloaded = {}

    unique_images = list(
        dict.fromkeys(body_images)
    )

    for index, url in enumerate(
        unique_images,
        start=1
    ):

        try:

            downloaded[url] = download_image(
                url,
                index
            )

        except Exception as e:

            raise RuntimeError(
                "Could not download body image:\n"
                f"{url}\n"
                f"Reason: {e}"
            )

    print(
        f"Downloaded images: "
        f"{len(downloaded)}/"
        f"{len(unique_images)}"
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

    login_selectors = [
        'a:has-text("Login")',
        'button:has-text("Login")',
        'a:has-text("Sign In")',
        'button:has-text("Sign In")',
        'a:has-text("Log in")',
        'button:has-text("Log in")',
    ]

    clicked = False

    for selector in login_selectors:

        try:

            locator = page.locator(selector)

            for i in range(locator.count()):

                item = locator.nth(i)

                if item.is_visible():

                    item.click()

                    clicked = True
                    break

            if clicked:
                break

        except Exception:
            continue

    if clicked:
        time.sleep(3)

    username_selectors = [
        'input[name="username"]',
        'input[name="login"]',
        'input[placeholder*="username" i]',
        'input[placeholder*="email" i]',
        'input[type="text"]',
    ]

    username_box = None

    for selector in username_selectors:

        try:

            locator = page.locator(selector)

            for i in range(locator.count()):

                item = locator.nth(i)

                if item.is_visible():

                    username_box = item
                    break

            if username_box:
                break

        except Exception:
            continue

    if not username_box:

        raise RuntimeError(
            "Serey username field not found."
        )

    username_box.fill(
        SEREY_LOGIN
    )

    password_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[placeholder*="password" i]',
    ]

    password_box = None

    for selector in password_selectors:

        try:

            locator = page.locator(selector)

            for i in range(locator.count()):

                item = locator.nth(i)

                if item.is_visible():

                    password_box = item
                    break

            if password_box:
                break

        except Exception:
            continue

    if not password_box:

        raise RuntimeError(
            "Serey password field not found."
        )

    password_box.fill(
        SEREY_PASSWORD
    )

    login_buttons = [
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Sign In")',
        'button[type="submit"]',
    ]

    submitted = False

    for selector in login_buttons:

        try:

            locator = page.locator(selector)

            for i in range(locator.count()):

                item = locator.nth(i)

                if item.is_visible():

                    item.click()

                    submitted = True
                    break

            if submitted:
                break

        except Exception:
            continue

    if not submitted:

        password_box.press("Enter")

    time.sleep(5)

    print(
        f"After login URL: {page.url}"
    )

    if "/login" in page.url.lower():

        raise RuntimeError(
            "Serey login failed."
        )

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!"
    )


# ============================================================
# WAIT FOR WRITE PAGE
# ============================================================

def wait_for_write_page(page):

    print()
    print("Waiting for Serey editor to load...")

    try:

        page.wait_for_load_state(
            "domcontentloaded",
            timeout=30000
        )

    except Exception:
        pass

    # Wait for React/Vue/etc. to render
    time.sleep(2)

    # Try network idle but don't fail if Serey keeps requests open
    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=15000
        )

    except Exception:
        pass

    time.sleep(2)

    print(
        f"Current write URL: {page.url}"
    )


# ============================================================
# DEBUG PAGE FIELDS
# ============================================================

def debug_page_fields(page):

    print()
    print("Scanning Serey page fields...")

    try:

        inputs = page.locator(
            "input, textarea"
        )

        count = inputs.count()

        print(
            f"Inputs/textareas found: {count}"
        )

        for i in range(count):

            item = inputs.nth(i)

            try:

                print(
                    f"Field {i}: "
                    f"tag={item.evaluate('(el) => el.tagName')} "
                    f"type={item.get_attribute('type')} "
                    f"name={item.get_attribute('name')} "
                    f"placeholder={item.get_attribute('placeholder')} "
                    f"aria={item.get_attribute('aria-label')}"
                )

            except Exception:
                pass

    except Exception as e:

        print(
            f"Could not scan fields: {e}"
        )


# ============================================================
# FIND TITLE
# ============================================================

def find_title_box(page):

    print()
    print("Looking for Serey title field...")

    selectors = [

        # Exact known selector
        'textarea[placeholder="Enter title..."]',
        'input[placeholder="Enter title..."]',

        # Placeholder variations
        'textarea[placeholder*="title" i]',
        'input[placeholder*="title" i]',

        # Names
        'textarea[name="title"]',
        'input[name="title"]',

        # ARIA
        'textarea[aria-label*="title" i]',
        'input[aria-label*="title" i]',

        # Common IDs/classes
        '#title',
        '.title-input',
        '.post-title',
    ]

    # First normal selector scan
    for selector in selectors:

        try:

            count = page.locator(selector).count()

            print(
                f"Checking: "
                f"{selector} -> {count}"
            )

            for i in range(count):

                item = page.locator(
                    selector
                ).nth(i)

                try:

                    if item.is_visible():

                        print(
                            f"✓ Title field found: "
                            f"{selector}"
                        )

                        return item

                except Exception:
                    pass

        except Exception:
            continue

    # ========================================================
    # Retry for dynamically loaded Serey editor
    # ========================================================

    print()
    print(
        "Title field not found yet. "
        "Waiting for dynamic page..."
    )

    for attempt in range(1, 16):

        print(
            f"Title search attempt "
            f"{attempt}/15"
        )

        time.sleep(2)

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
                            f"✓ Title field found "
                            f"after waiting: "
                            f"{selector}"
                        )

                        return item

            except Exception:
                continue

    # ========================================================
    # Generic fallback:
    # Find visible input/textarea that is NOT password/file
    # ========================================================

    print()
    print(
        "Trying generic title-field detection..."
    )

    try:

        locator = page.locator(
            "input, textarea"
        )

        count = locator.count()

        for i in range(count):

            item = locator.nth(i)

            try:

                if not item.is_visible():
                    continue

                tag = item.evaluate(
                    "(el) => el.tagName.toLowerCase()"
                )

                field_type = (
                    item.get_attribute("type")
                    or ""
                ).lower()

                placeholder = (
                    item.get_attribute(
                        "placeholder"
                    )
                    or ""
                ).lower()

                name = (
                    item.get_attribute("name")
                    or ""
                ).lower()

                if field_type in [
                    "password",
                    "file",
                    "hidden"
                ]:
                    continue

                if (
                    "title" in placeholder
                    or
                    "title" in name
                ):

                    print(
                        "✓ Generic title field found"
                    )

                    return item

            except Exception:
                continue

    except Exception:
        pass

    print()
    print(
        "✗ Title field could not be found."
    )

    debug_page_fields(page)

    return None


# ============================================================
# FIND EDITOR
# ============================================================

def find_editor(page):

    selectors = [
        '[contenteditable="true"]',
        '.ProseMirror',
        '[role="textbox"]',
        'textarea[placeholder="Enter content..."]',
        'textarea[placeholder*="Enter content" i]',
        'textarea[name="content"]',
        'textarea[placeholder*="content" i]',
    ]

    print()
    print("Looking for content editor...")

    for attempt in range(1, 16):

        for selector in selectors:

            try:

                locator = page.locator(selector)

                for i in range(locator.count()):

                    item = locator.nth(i)

                    if item.is_visible():

                        print(
                            f"✓ Editor found: "
                            f"{selector}"
                        )

                        return item

            except Exception:
                continue

        print(
            f"Editor search attempt "
            f"{attempt}/15"
        )

        time.sleep(1)

    return None


# ============================================================
# FILE INPUTS
# ============================================================

def get_file_inputs(page):

    inputs = []

    locator = page.locator(
        'input[type="file"]'
    )

    for i in range(locator.count()):

        item = locator.nth(i)

        try:

            inputs.append({
                "index": i,
                "locator": item,
                "accept": item.get_attribute(
                    "accept"
                ),
                "name": item.get_attribute(
                    "name"
                ),
                "multiple": item.get_attribute(
                    "multiple"
                ),
            })

        except Exception:
            pass

    return inputs


def print_file_inputs(page):

    inputs = get_file_inputs(page)

    print(
        f"File inputs detected: "
        f"{len(inputs)}"
    )

    for item in inputs:

        print(
            f"File input {item['index']}: "
            f"accept={item['accept']} "
            f"name={item['name']} "
            f"multiple={item['multiple']}"
        )

    return inputs


# ============================================================
# THUMBNAIL
# ============================================================

def upload_thumbnail(
    page,
    image_path
):

    print()
    print("Uploading thumbnail...")

    inputs = print_file_inputs(page)

    if not inputs:

        print(
            "No file input currently visible."
        )

        return False

    # Try first suitable image input
    for item in inputs:

        accept = (
            item["accept"]
            or ""
        ).lower()

        if (
            "image" in accept
            or
            accept == ""
        ):

            try:

                item["locator"].set_input_files(
                    image_path
                )

                print(
                    f"✓ Thumbnail selected "
                    f"using file input "
                    f"{item['index']}"
                )

                time.sleep(2)

                return True

            except Exception as e:

                print(
                    f"Thumbnail input "
                    f"{item['index']} failed: {e}"
                )

    return False


# ============================================================
# EDITOR IMAGE COUNT
# ============================================================

def editor_image_count(editor):

    try:

        tag = editor.evaluate(
            "(el) => el.tagName.toLowerCase()"
        )

        if tag == "textarea":
            return 0

        return editor.locator(
            "img"
        ).count()

    except Exception:

        return 0


# ============================================================
# EDITOR HTML
# ============================================================

def get_editor_html(editor):

    try:

        return editor.evaluate(
            "(el) => el.innerHTML"
        )

    except Exception:

        return ""


# ============================================================
# FIND BODY IMAGE INPUT
# ============================================================

def find_body_image_input(
    page,
    before_count
):

    inputs = print_file_inputs(page)

    if not inputs:

        print(
            "No file input found."
        )

        return None

    # ========================================================
    # Prefer image input that is NOT obviously thumbnail
    # ========================================================

    candidates = []

    for item in inputs:

        accept = (
            item["accept"]
            or ""
        ).lower()

        name = (
            item["name"]
            or ""
        ).lower()

        if (
            "image" in accept
            or
            accept == ""
        ):

            candidates.append(item)

    print(
        f"Possible image inputs: "
        f"{len(candidates)}"
    )

    # If there are multiple inputs, body uploader is often
    # the second one, but don't blindly assume it.
    if len(candidates) >= 2:

        item = candidates[1]

        print(
            f"✓ Trying body image input "
            f"{item['index']}"
        )

        return item["locator"]

    # ========================================================
    # Try names related to body/content/editor/upload
    # ========================================================

    for item in candidates:

        name = (
            item["name"]
            or ""
        ).lower()

        if any(
            word in name
            for word in [
                "body",
                "content",
                "editor",
                "upload",
                "image"
            ]
        ):

            print(
                f"✓ Body image candidate: "
                f"input {item['index']}"
            )

            return item["locator"]

    # ========================================================
    # Last fallback
    # ========================================================

    if candidates:

        print(
            f"✓ Using image input "
            f"{candidates[-1]['index']} "
            f"as fallback"
        )

        return candidates[-1]["locator"]

    return None


# ============================================================
# UPLOAD BODY IMAGE
# ============================================================

def upload_body_image(
    page,
    editor,
    image_path,
    original_url=None
):

    print()
    print(
        f"Uploading body image: "
        f"{image_path}"
    )

    before_count = (
        editor_image_count(
            editor
        )
    )

    before_html = (
        get_editor_html(
            editor
        )
    )

    print(
        f"Images in editor before upload: "
        f"{before_count}"
    )

    try:
        editor.click()
    except Exception:
        pass

    body_input = find_body_image_input(
        page,
        before_count
    )

    if not body_input:

        raise RuntimeError(
            "Serey body image input "
            "not found."
        )

    try:

        body_input.set_input_files(
            image_path
        )

        print(
            "✓ Body image selected"
        )

    except Exception as e:

        raise RuntimeError(
            "Could not select body image: "
            f"{e}"
        )

    # Wait for upload/insertion
    for second in range(1, 21):

        time.sleep(1)

        after_count = (
            editor_image_count(
                editor
            )
        )

        if after_count > before_count:

            print(
                f"✓ Body image inserted "
                f"into editor "
                f"({before_count} -> "
                f"{after_count})"
            )

            return True

        after_html = (
            get_editor_html(
                editor
            )
        )

        if (
            after_html != before_html
            and
            "<img" in after_html.lower()
        ):

            print(
                "✓ Body image inserted "
                "into editor HTML."
            )

            return True

        print(
            f"Waiting for image upload "
            f"{second}/20..."
        )

    raise RuntimeError(
        "Serey body image upload "
        "could not be verified."
    )


# ============================================================
# FILL TEXT
# ============================================================

def type_editor_text(
    page,
    editor,
    text
):

    if not text:
        return

    try:

        tag = editor.evaluate(
            "(el) => el.tagName.toLowerCase()"
        )

    except Exception:

        tag = ""

    if tag == "textarea":

        current = editor.input_value()

        editor.fill(
            current + text
        )

    else:

        editor.click()

        page.keyboard.insert_text(
            text
        )


# ============================================================
# FILL BODY + IMAGES
# ============================================================

def fill_body_with_uploaded_images(
    page,
    editor,
    body,
    downloaded_images
):

    parts = split_body_with_images(body)

    has_images = any(
        part_type == "image"
        for part_type, value in parts
    )

    if not has_images:

        try:

            tag = editor.evaluate(
                "(el) => el.tagName.toLowerCase()"
            )

            if tag == "textarea":

                editor.fill(body)

            else:

                editor.click()

                page.keyboard.insert_text(
                    body
                )

        except Exception as e:

            raise RuntimeError(
                f"Could not fill body: {e}"
            )

        print("✓ Body filled")

        return

    try:

        tag = editor.evaluate(
            "(el) => el.tagName.toLowerCase()"
        )

        if tag == "textarea":

            editor.fill("")

        else:

            editor.click()

            page.keyboard.press("Control+A")

            page.keyboard.press("Backspace")

    except Exception:
        pass

    image_number = 0

    for part_type, value in parts:

        if part_type == "text":

            type_editor_text(
                page,
                editor,
                value
            )

        elif part_type == "image":

            image_number += 1

            image_path = (
                downloaded_images.get(value)
            )

            if not image_path:

                raise RuntimeError(
                    "Downloaded image "
                    "file not found:\n"
                    f"{value}"
                )

            print()
            print(
                f"Body image "
                f"{image_number}:"
            )

            print(value)

            upload_body_image(
                page,
                editor,
                image_path,
                value
            )

    print()
    print(
        f"✓ Body completed with "
        f"{image_number} "
        f"uploaded image(s)"
    )


# ============================================================
# PUBLISH BUTTON
# ============================================================

def find_publish_button(page):

    selectors = [
        'button:has-text("Publish")',
        'button:has-text("publish")',
        'button[type="submit"]',
    ]

    for attempt in range(1, 11):

        for selector in selectors:

            try:

                locator = page.locator(selector)

                for i in range(locator.count()):

                    item = locator.nth(i)

                    if item.is_visible():

                        return item

            except Exception:
                continue

        time.sleep(1)

    return None


# ============================================================
# VERIFY PUBLISH
# ============================================================

def verify_publish(page):

    time.sleep(5)

    current_url = page.url

    if "/write/new" not in current_url:

        print(
            f"✓ Publish verified by URL: "
            f"{current_url}"
        )

        return True

    confirmation_texts = [
        "Published",
        "published",
        "Post published",
        "Successfully published",
        "successfully",
    ]

    for text_value in confirmation_texts:

        try:

            locator = page.get_by_text(
                text_value,
                exact=False
            )

            for i in range(locator.count()):

                if locator.nth(i).is_visible():

                    print(
                        "✓ Publish confirmation found."
                    )

                    return True

        except Exception:
            continue

    return False


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish(
    page,
    post
):

    title = post["title"]

    body = clean_post(
        post["body"]
    )

    print()
    print("=" * 60)
    print("Publishing post")
    print("=" * 60)

    print(
        f"Title: {title}"
    )

    print(
        f"Body length: "
        f"{len(body)} characters"
    )

    # ========================================================
    # OPEN WRITE PAGE
    # ========================================================

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    print(
        f"Write page: {page.url}"
    )

    wait_for_write_page(page)

    # ========================================================
    # TITLE
    # ========================================================

    title_box = find_title_box(page)

    if not title_box:

        raise RuntimeError(
            "Serey title input not found."
        )

    try:

        title_box.click()

        title_box.fill("")

        title_box.fill(title)

    except Exception as e:

        raise RuntimeError(
            f"Could not fill title: {e}"
        )

    print("✓ Title filled")

    # ========================================================
    # EDITOR
    # ========================================================

    editor = find_editor(page)

    if not editor:

        raise RuntimeError(
            "Serey content editor "
            "not found."
        )

    # ========================================================
    # BODY IMAGES
    # ========================================================

    body_images = extract_body_images(body)

    print(
        f"Images found in post: "
        f"{len(body_images)}"
    )

    downloaded_images = {}

    if body_images:

        downloaded_images = (
            download_body_images(
                body_images
            )
        )

    # ========================================================
    # BODY
    # ========================================================

    fill_body_with_uploaded_images(
        page,
        editor,
        body,
        downloaded_images
    )

    # ========================================================
    # THUMBNAIL
    # ========================================================

    thumbnail_path = None

    if body_images:

        thumbnail_path = (
            downloaded_images.get(
                body_images[0]
            )
        )

    else:

        metadata_images = (
            extract_metadata_images(
                post
            )
        )

        if metadata_images:

            try:

                thumbnail_path = (
                    download_image(
                        metadata_images[0],
                        1
                    )
                )

            except Exception as e:

                print(
                    "Thumbnail fallback "
                    f"download failed: {e}"
                )

    if thumbnail_path:

        upload_thumbnail(
            page,
            thumbnail_path
        )

    # ========================================================
    # PUBLISH
    # ========================================================

    publish_button = (
        find_publish_button(page)
    )

    if not publish_button:

        raise RuntimeError(
            "Publish button not found."
        )

    print()
    print("Clicking Publish...")

    publish_button.click()

    time.sleep(3)

    # ========================================================
    # CONFIRM DIALOG
    # ========================================================

    confirmation_selectors = [
        'button:has-text("Confirm")',
        'button:has-text("confirm")',
        'button:has-text("Yes")',
        'button:has-text("Publish")',
    ]

    for selector in confirmation_selectors:

        try:

            locator = page.locator(selector)

            for i in range(locator.count()):

                item = locator.nth(i)

                if not item.is_visible():
                    continue

                try:

                    item.click(
                        timeout=2000
                    )

                    time.sleep(3)

                    break

                except Exception:
                    pass

        except Exception:
            pass

    # ========================================================
    # VERIFY
    # ========================================================

    if not verify_publish(page):

        raise RuntimeError(
            "Publish could not be verified."
        )

    print()
    print(
        f"✓ POST PUBLISHED: "
        f"{post['id']}"
    )

    return True


# ============================================================
# CLEAN TEMPORARY IMAGES
# ============================================================

def cleanup_images():

    print()
    print(
        "Cleaning temporary images..."
    )

    for path in Path(".").glob(
        f"{IMAGE_PREFIX}*"
    ):

        try:

            path.unlink()

            print(
                f"Removed: "
                f"{path.name}"
            )

        except Exception as e:

            print(
                f"Could not remove "
                f"{path}: {e}"
            )


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

    print()

    synced = load_synced()

    print(
        f"Previously synced: "
        f"{len(synced)}"
    )

    print(
        f"Getting recent posts from "
        f"@{STEEM_USERNAME}..."
    )

    posts = get_posts()

    print()

    print(
        f"Total posts in last "
        f"{DAYS_TO_SYNC} days: "
        f"{len(posts)}"
    )

    if not posts:

        print(
            "No posts found."
        )

        return

    print(
        f"Oldest: "
        f"{posts[0]['created']} "
        f"{posts[0]['id']}"
    )

    print(
        f"Newest: "
        f"{posts[-1]['created']} "
        f"{posts[-1]['id']}"
    )

    unsynced = [
        post
        for post in posts
        if post["id"] not in synced
    ]

    print(
        f"Unsynced posts: "
        f"{len(unsynced)}"
    )

    if not unsynced:

        print(
            "✓ No unsynced posts."
        )

        return

    selected = unsynced[
        :POSTS_PER_RUN
    ]

    print(
        f"Posts selected this run: "
        f"{len(selected)}"
    )

    for post in selected:

        print()
        print("-" * 60)

        print(
            f"Selected: "
            f"{post['id']}"
        )

        print(
            f"Created: "
            f"{post['created']}"
        )

        print(
            f"Title: "
            f"{post['title']}"
        )

        print("-" * 60)

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

            login(page)

            print()
            print(
                "Starting sync:"
            )

            for post in selected:

                print()
                print("=" * 60)

                print(
                    post["id"]
                )

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
                            f"{post['id']}"
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

                    # Failed post is NOT saved.

        finally:

            browser.close()

            cleanup_images()

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
