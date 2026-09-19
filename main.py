import os
import re
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

SEREY_PASSWORD = os.environ["SEREY_PASSWORD"].strip()

# Login / writing may use bengali.serey.io
SEREY = "https://bengali.serey.io"

NEW_POST = f"{SEREY}/write/new"

# Published URL can be serey.io
PUBLISHED_HOSTS = {
    "serey.io",
    "www.serey.io",
    "bengali.serey.io",
}

SYNC_FILE = "synced_posts.json"

POSTS_PER_RUN = 1

DAYS_TO_SYNC = 365

REQUEST_TIMEOUT = 30

MAX_IMAGE_SIZE = 30 * 1024 * 1024

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://api.steem.fans",
]


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

            if "result" in data:

                print(
                    f"✓ RPC success: {node}"
                )

                return data["result"]

            print(
                f"✗ RPC error: {data}"
            )

        except Exception as e:

            last_error = e

            print(
                f"✗ RPC failed: {node}"
            )

            print(e)

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
            f"Warning: could not load "
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
# IMAGE REGEX
# ============================================================

IMAGE_MARKDOWN_RE = re.compile(
    r'!\[[^\]]*\]\(\s*(https?://[^)\s]+)'
    r'(?:\s+"[^"]*")?\s*\)',
    re.IGNORECASE
)

HTML_IMAGE_RE = re.compile(
    r'<img\b[^>]*\bsrc\s*=\s*["\']'
    r'(https?://[^"\']+)'
    r'["\'][^>]*>',
    re.IGNORECASE
)


# ============================================================
# EXTRACT IMAGES
# ============================================================

def extract_images_from_body(body):

    images = []

    if not body:
        return images

    for url in IMAGE_MARKDOWN_RE.findall(body):

        if url not in images:
            images.append(url)

    for url in HTML_IMAGE_RE.findall(body):

        if url not in images:
            images.append(url)

    return images


# ============================================================
# FIRST IMAGE = THUMBNAIL
# ============================================================

def get_first_image(post):

    body = post.get(
        "body",
        ""
    )

    body_images = extract_images_from_body(
        body
    )

    if body_images:

        print(
            "✓ First body image found:"
        )

        print(
            body_images[0]
        )

        return body_images[0]

    # Metadata fallback
    try:

        metadata_raw = post.get(
            "json_metadata",
            ""
        )

        if isinstance(
            metadata_raw,
            str
        ):

            metadata = json.loads(
                metadata_raw
            )

        else:

            metadata = metadata_raw

        if isinstance(
            metadata,
            dict
        ):

            image_list = metadata.get(
                "image",
                []
            )

            if isinstance(
                image_list,
                str
            ):

                image_list = [
                    image_list
                ]

            if isinstance(
                image_list,
                list
            ):

                for image in image_list:

                    if (
                        isinstance(
                            image,
                            str
                        )
                        and image.startswith(
                            "http"
                        )
                    ):

                        print(
                            "✓ First metadata "
                            "image found:"
                        )

                        print(image)

                        return image

    except Exception as e:

        print(
            f"Metadata image check failed: {e}"
        )

    print(
        "⚠ No image found for thumbnail."
    )

    return None


# ============================================================
# CLEAN ARTICLE
# ============================================================

def clean_article(body):

    if not body:
        return ""

    text = body

    # HTML comments
    text = re.sub(
        r'<!--.*?-->',
        '',
        text,
        flags=re.DOTALL
    )

    # Remove Markdown images
    text = IMAGE_MARKDOWN_RE.sub(
        '',
        text
    )

    # Remove HTML images
    text = HTML_IMAGE_RE.sub(
        '',
        text
    )

    # Remove div
    text = re.sub(
        r'</?div\b[^>]*>',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Remove paragraph tags
    text = re.sub(
        r'</?p\b[^>]*>',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Remove span
    text = re.sub(
        r'</?span\b[^>]*>',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Remove center
    text = re.sub(
        r'</?center\b[^>]*>',
        '',
        text,
        flags=re.IGNORECASE
    )

    # BR -> newline
    text = re.sub(
        r'<br\s*/?>',
        '\n',
        text,
        flags=re.IGNORECASE
    )

    # HTML links -> visible text
    text = re.sub(
        r'<a\b[^>]*>(.*?)</a>',
        r'\1',
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Remove remaining HTML
    text = re.sub(
        r'<[^>]+>',
        '',
        text
    )

    # Markdown links -> visible text
    text = re.sub(
        r'\[([^\]]+)\]\(\s*https?://[^)\s]+[^)]*\)',
        r'\1',
        text
    )

    # Markdown headings
    text = re.sub(
        r'^\s{0,3}#{1,6}\s*',
        '',
        text,
        flags=re.MULTILINE
    )

    # Bold / italic
    text = re.sub(
        r'\*\*\*(.*?)\*\*\*',
        r'\1',
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r'\*\*(.*?)\*\*',
        r'\1',
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r'__(.*?)__',
        r'\1',
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r'(?<!\*)\*([^*\n]+)\*(?!\*)',
        r'\1',
        text
    )

    text = re.sub(
        r'(?<!_)_([^_\n]+)_(?!_)',
        r'\1',
        text
    )

    # Horizontal rules
    text = re.sub(
        r'^\s*([-*_])(?:\s*\1){2,}\s*$',
        '',
        text,
        flags=re.MULTILINE
    )

    # Excessive blank lines
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

    # Trim every line
    lines = []

    for line in text.splitlines():

        line = line.strip()

        lines.append(line)

    text = "\n".join(lines)

    return text.strip()


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def detect_extension(url, response):

    content_type = (
        response.headers.get(
            "content-type",
            ""
        ).lower()
    )

    if "png" in content_type:
        return ".png"

    if "webp" in content_type:
        return ".webp"

    if "gif" in content_type:
        return ".gif"

    if (
        "jpeg" in content_type
        or "jpg" in content_type
    ):
        return ".jpg"

    path = url.lower().split("?")[0]

    for ext in [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif"
    ]:

        if path.endswith(ext):
            return ext

    return ".jpg"


def download_image(
    url,
    filename
):

    print()
    print(
        "Downloading thumbnail:"
    )

    print(url)

    try:

        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            stream=True,
            headers={
                "User-Agent":
                    "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        extension = detect_extension(
            url,
            response
        )

        path = Path(
            Path(filename).stem
            + extension
        )

        total = 0

        with open(
            path,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=65536
            ):

                if not chunk:
                    continue

                total += len(chunk)

                if total > MAX_IMAGE_SIZE:

                    try:
                        path.unlink()
                    except Exception:
                        pass

                    print(
                        "✗ Thumbnail too large"
                    )

                    return None

                f.write(chunk)

        if total == 0:

            print(
                "✗ Empty image"
            )

            return None

        print(
            f"✓ Thumbnail downloaded: "
            f"{path.name} "
            f"({total} bytes)"
        )

        return str(path)

    except Exception as e:

        print(
            f"✗ Thumbnail download failed: "
            f"{e}"
        )

        return None


# ============================================================
# DEBUG PAGE
# ============================================================

def debug_page(
    page,
    filename="serey_debug"
):

    print()
    print(
        "=" * 60
    )

    print(
        "SEREY DEBUG"
    )

    print(
        "=" * 60
    )

    print(
        "Current URL:",
        page.url
    )

    try:

        inputs = page.locator(
            "input, textarea"
        )

        print(
            "Inputs:",
            inputs.count()
        )

        for i in range(
            inputs.count()
        ):

            try:

                item = inputs.nth(i)

                print(
                    f"[{i}] "
                    f"tag={item.evaluate('(e)=>e.tagName')} "
                    f"type={item.get_attribute('type')} "
                    f"name={item.get_attribute('name')} "
                    f"placeholder={item.get_attribute('placeholder')} "
                    f"accept={item.get_attribute('accept')} "
                    f"aria={item.get_attribute('aria-label')}"
                )

            except Exception:
                pass

    except Exception:
        pass

    try:

        page.screenshot(
            path=f"{filename}.png",
            full_page=True
        )

        print(
            f"✓ Screenshot saved: "
            f"{filename}.png"
        )

    except Exception as e:

        print(
            f"Screenshot failed: {e}"
        )

    try:

        html = page.locator(
            "body"
        ).evaluate(
            "(e) => e.outerHTML"
        )

        with open(
            f"{filename}.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(html)

        print(
            f"✓ HTML saved: "
            f"{filename}.html"
        )

    except Exception as e:

        print(
            f"HTML save failed: {e}"
        )


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print(
        "Logging into Serey..."
    )

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        4000
    )

    if "/login" not in page.url.lower():

        print(
            "After login URL:",
            page.url
        )

        print(
            "✓ LOGGED INTO SEREY SUCCESSFULLY!"
        )

        return True

    username_box = None
    password_box = None

    username_selectors = [
        'input[placeholder*="username" i]',
        'input[placeholder*="email" i]',
        'input[name="username"]',
        'input[name="email"]',
        'input[type="text"]',
    ]

    password_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[placeholder*="password" i]',
    ]

    for selector in username_selectors:

        try:

            loc = page.locator(
                selector
            )

            for i in range(
                loc.count()
            ):

                item = loc.nth(i)

                if (
                    item.is_visible()
                    and item.is_enabled()
                ):

                    username_box = item

                    break

            if username_box:
                break

        except Exception:
            pass

    for selector in password_selectors:

        try:

            loc = page.locator(
                selector
            )

            for i in range(
                loc.count()
            ):

                item = loc.nth(i)

                if (
                    item.is_visible()
                    and item.is_enabled()
                ):

                    password_box = item

                    break

            if password_box:
                break

        except Exception:
            pass

    if not username_box or not password_box:

        print(
            "✗ Login fields not found"
        )

        debug_page(
            page,
            "serey_login_debug"
        )

        return False

    username_box.fill(
        SEREY_LOGIN
    )

    password_box.fill(
        SEREY_PASSWORD
    )

    login_button = None

    selectors = [
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button[type="submit"]',
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            for i in range(
                loc.count()
            ):

                item = loc.nth(i)

                if (
                    item.is_visible()
                    and item.is_enabled()
                ):

                    login_button = item

                    break

            if login_button:
                break

        except Exception:
            pass

    if not login_button:

        print(
            "✗ Login button not found"
        )

        return False

    login_button.click()

    page.wait_for_timeout(
        5000
    )

    print(
        "After login URL:",
        page.url
    )

    if "/login" in page.url.lower():

        print(
            "✗ LOGIN FAILED"
        )

        return False

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!"
    )

    return True


# ============================================================
# TITLE
# ============================================================

def find_title_box(page):

    print()
    print(
        "Looking for Serey title field..."
    )

    selectors = [

        'textarea[placeholder="Enter title..."]',
        'input[placeholder="Enter title..."]',

        'textarea[placeholder*="Enter title" i]',
        'input[placeholder*="Enter title" i]',

        'textarea[name="title"]',
        'input[name="title"]',

        'textarea[aria-label*="title" i]',
        'input[aria-label*="title" i]',

        'textarea[id*="title" i]',
        'input[id*="title" i]',
    ]

    deadline = time.time() + 30

    while time.time() < deadline:

        for selector in selectors:

            try:

                loc = page.locator(
                    selector
                )

                count = loc.count()

                print(
                    f"Checking: "
                    f"{selector} -> {count}"
                )

                for i in range(count):

                    item = loc.nth(i)

                    if (
                        item.is_visible()
                        and item.is_enabled()
                    ):

                        print(
                            f"✓ Title field found: "
                            f"{selector}"
                        )

                        return item

            except Exception:
                pass

        time.sleep(0.5)

    print(
        "✗ Serey title input not found"
    )

    debug_page(
        page,
        "serey_title_debug"
    )

    return None


# ============================================================
# EDITOR
# ============================================================

def find_editor(page):

    print()
    print(
        "Looking for content editor..."
    )

    selectors = [
        '[contenteditable="true"]',
        '.ProseMirror',
        '[role="textbox"][contenteditable="true"]',
    ]

    deadline = time.time() + 30

    while time.time() < deadline:

        for selector in selectors:

            try:

                loc = page.locator(
                    selector
                )

                for i in range(
                    loc.count()
                ):

                    item = loc.nth(i)

                    if (
                        item.is_visible()
                        and item.is_enabled()
                    ):

                        print(
                            f"✓ Editor found: "
                            f"{selector}"
                        )

                        return item

            except Exception:
                pass

        time.sleep(0.5)

    print(
        "✗ Editor not found"
    )

    debug_page(
        page,
        "serey_editor_debug"
    )

    return None


# ============================================================
# THUMBNAIL BUTTON
# ============================================================

def find_thumbnail_buttons(page):

    result = []

    try:

        buttons = page.locator(
            "button, [role='button']"
        )

        for i in range(
            buttons.count()
        ):

            try:

                button = buttons.nth(i)

                if not button.is_visible():
                    continue

                aria = (
                    button.get_attribute(
                        "aria-label"
                    ) or ""
                ).lower()

                title = (
                    button.get_attribute(
                        "title"
                    ) or ""
                ).lower()

                text = ""

                try:

                    text = button.inner_text(
                        timeout=500
                    ).strip().lower()

                except Exception:
                    pass

                combined = " ".join([
                    aria,
                    title,
                    text
                ])

                if any(
                    word in combined
                    for word in [
                        "thumbnail",
                        "cover",
                        "featured image",
                        "featured"
                    ]
                ):

                    result.append(
                        button
                    )

            except Exception:
                pass

    except Exception:
        pass

    return result


# ============================================================
# FILE INPUTS
# ============================================================

def get_file_inputs(page):

    result = []

    try:

        loc = page.locator(
            'input[type="file"]'
        )

        count = loc.count()

        print(
            f"File inputs detected: "
            f"{count}"
        )

        for i in range(count):

            item = loc.nth(i)

            accept = (
                item.get_attribute(
                    "accept"
                ) or ""
            )

            name = (
                item.get_attribute(
                    "name"
                ) or ""
            )

            print(
                f"File input {i}: "
                f"accept={accept} "
                f"name={name}"
            )

            result.append(
                item
            )

    except Exception as e:

        print(
            f"File input error: {e}"
        )

    return result


# ============================================================
# UPLOAD THUMBNAIL
# ============================================================

def upload_thumbnail(
    page,
    thumbnail_path
):

    if not thumbnail_path:

        print(
            "⚠ No thumbnail available."
        )

        return True

    print()
    print(
        "=" * 60
    )

    print(
        "Uploading FIRST IMAGE as thumbnail"
    )

    print(
        "=" * 60
    )

    print(
        f"Thumbnail file: "
        f"{thumbnail_path}"
    )

    # --------------------------------------------------------
    # Dedicated thumbnail / cover button
    # --------------------------------------------------------

    buttons = find_thumbnail_buttons(
        page
    )

    print(
        f"Thumbnail buttons found: "
        f"{len(buttons)}"
    )

    for button in buttons:

        try:

            with page.expect_file_chooser(
                timeout=4000
            ) as chooser_info:

                button.click()

            chooser = chooser_info.value

            chooser.set_files(
                thumbnail_path
            )

            print(
                "✓ Thumbnail selected "
                "through file chooser"
            )

            page.wait_for_timeout(
                2000
            )

            return True

        except Exception as e:

            print(
                f"Thumbnail button attempt "
                f"failed: {e}"
            )

    # --------------------------------------------------------
    # Direct input
    # --------------------------------------------------------

    inputs = get_file_inputs(
        page
    )

    thumbnail_inputs = []

    for i, item in enumerate(inputs):

        try:

            accept = (
                item.get_attribute(
                    "accept"
                ) or ""
            ).lower()

            name = (
                item.get_attribute(
                    "name"
                ) or ""
            ).lower()

            input_id = (
                item.get_attribute(
                    "id"
                ) or ""
            ).lower()

            combined = " ".join([
                accept,
                name,
                input_id
            ])

            if any(
                word in combined
                for word in [
                    "thumbnail",
                    "cover",
                    "featured"
                ]
            ):

                thumbnail_inputs.append(
                    (i, item)
                )

        except Exception:
            pass

    if thumbnail_inputs:

        index, item = thumbnail_inputs[0]

        try:

            item.set_input_files(
                thumbnail_path
            )

            print(
                f"✓ Thumbnail uploaded "
                f"using input {index}"
            )

            page.wait_for_timeout(
                2000
            )

            return True

        except Exception as e:

            print(
                f"Thumbnail input failed: "
                f"{e}"
            )

    # --------------------------------------------------------
    # Single input fallback
    # --------------------------------------------------------

    if len(inputs) == 1:

        print(
            "Only one image input exists."
        )

        print(
            "Using it for thumbnail."
        )

        try:

            inputs[0].set_input_files(
                thumbnail_path
            )

            print(
                "✓ Thumbnail uploaded "
                "using single image input"
            )

            page.wait_for_timeout(
                2000
            )

            return True

        except Exception as e:

            print(
                f"Single thumbnail input "
                f"failed: {e}"
            )

    print(
        "⚠ Thumbnail upload could not "
        "be confirmed."
    )

    debug_page(
        page,
        "serey_thumbnail_debug"
    )

    return True


# ============================================================
# TYPE ARTICLE
# ============================================================

def type_article(
    page,
    editor,
    article
):

    print()
    print(
        "Entering clean article..."
    )

    print(
        f"Clean article length: "
        f"{len(article)} characters"
    )

    editor.click()

    page.keyboard.insert_text(
        article
    )

    print(
        "✓ Clean article inserted"
    )


# ============================================================
# FIND PUBLISH BUTTON
# ============================================================

def find_publish_button(page):

    selectors = [
        'button:has-text("Publish")',
        'button:has-text("Post")',
        'button:has-text("Publish Post")',
        '[role="button"]:has-text("Publish")',
        '[role="button"]:has-text("Post")',
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            for i in range(
                loc.count()
            ):

                button = loc.nth(i)

                if (
                    button.is_visible()
                    and button.is_enabled()
                ):

                    return button

        except Exception:
            pass

    return None


# ============================================================
# CHECK PUBLISHED URL
# ============================================================

def is_published_post_url(url):

    try:

        parsed = urlparse(url)

        hostname = (
            parsed.hostname or ""
        ).lower()

        path = (
            parsed.path or ""
        ).lower()

        # Example:
        # /authors/mamun/9xl6x0p71a...
        if hostname not in PUBLISHED_HOSTS:
            return False

        if not path.startswith(
            "/authors/"
        ):
            return False

        parts = [
            x
            for x in path.split("/")
            if x
        ]

        # Expected:
        # authors / username / post-id
        if len(parts) < 3:
            return False

        if parts[0] != "authors":
            return False

        if not parts[1]:
            return False

        if not parts[2]:
            return False

        return True

    except Exception:

        return False


# ============================================================
# VERIFY PUBLISHED PAGE
# ============================================================

def verify_published_page(
    page,
    expected_title
):

    print()
    print(
        "=" * 60
    )

    print(
        "VERIFYING SEREY PUBLISHED URL"
    )

    print(
        "=" * 60
    )

    # Give Serey time to redirect
    deadline = time.time() + 30

    published_url = None

    while time.time() < deadline:

        current_url = page.url

        print(
            "Current URL:",
            current_url
        )

        if is_published_post_url(
            current_url
        ):

            published_url = current_url

            print(
                "✓ Published URL detected:"
            )

            print(
                published_url
            )

            break

        page.wait_for_timeout(
            1000
        )

    if not published_url:

        print(
            "✗ Published post URL was "
            "not detected."
        )

        print(
            "Expected format:"
        )

        print(
            "https://serey.io/authors/"
            "username/post-id"
        )

        return False, None

    # --------------------------------------------------------
    # Load / verify published page
    # --------------------------------------------------------

    try:

        print(
            "Opening published post "
            "for verification..."
        )

        page.goto(
            published_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(
            3000
        )

    except Exception as e:

        print(
            f"⚠ Could not reload "
            f"published page: {e}"
        )

        # URL itself was valid.
        # Continue with URL verification.
        return True, published_url

    final_url = page.url

    print(
        "Final published URL:",
        final_url
    )

    if not is_published_post_url(
        final_url
    ):

        print(
            "✗ Final URL is not a valid "
            "Serey author post URL."
        )

        return False, None

    # --------------------------------------------------------
    # Check page title/content
    # --------------------------------------------------------

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        if not body_text.strip():

            print(
                "✗ Published page body "
                "is empty."
            )

            return False, None

        print(
            "✓ Published page contains "
            "visible content."
        )

    except Exception as e:

        print(
            f"⚠ Could not inspect "
            f"published page body: {e}"
        )

    # --------------------------------------------------------
    # Check expected title
    # --------------------------------------------------------

    if expected_title:

        try:

            title_found = (
                expected_title.lower()
                in body_text.lower()
            )

            if title_found:

                print(
                    "✓ Published title "
                    "confirmed."
                )

            else:

                print(
                    "⚠ Expected title was "
                    "not found in visible "
                    "page text."
                )

        except Exception:
            pass

    print()
    print(
        "✓✓✓ PUBLISHED POST VERIFIED ✓✓✓"
    )

    print(
        "Published URL:"
    )

    print(
        published_url
    )

    return True, published_url


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish_post(
    page,
    post
):

    title = (
        post.get(
            "title",
            ""
        ).strip()
    )

    original_body = (
        post.get(
            "body",
            ""
        )
    )

    # --------------------------------------------------------
    # First image
    # --------------------------------------------------------

    first_image = get_first_image(
        post
    )

    # --------------------------------------------------------
    # Clean article
    # --------------------------------------------------------

    article = clean_article(
        original_body
    )

    print()
    print(
        "=" * 60
    )

    print(
        "Publishing post"
    )

    print(
        "=" * 60
    )

    print(
        f"Title: {title}"
    )

    print(
        f"Original body length: "
        f"{len(original_body)}"
    )

    print(
        f"Clean body length: "
        f"{len(article)}"
    )

    print(
        f"First image: "
        f"{first_image}"
    )

    # --------------------------------------------------------
    # Open write page
    # --------------------------------------------------------

    print(
        f"Write page: {NEW_POST}"
    )

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        5000
    )

    print(
        "Current write URL:",
        page.url
    )

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title_box = find_title_box(
        page
    )

    if not title_box:

        raise RuntimeError(
            "Serey title input not found."
        )

    title_box.click()

    title_box.fill(
        title
    )

    print(
        "✓ Title filled"
    )

    # --------------------------------------------------------
    # Editor
    # --------------------------------------------------------

    editor = find_editor(
        page
    )

    if not editor:

        raise RuntimeError(
            "Serey content editor not found."
        )

    # --------------------------------------------------------
    # First image only
    # --------------------------------------------------------

    thumbnail_path = None

    if first_image:

        thumbnail_path = download_image(
            first_image,
            "steem_thumbnail"
        )

    if thumbnail_path:

        upload_thumbnail(
            page,
            thumbnail_path
        )

    else:

        print(
            "⚠ No thumbnail will be uploaded."
        )

    # --------------------------------------------------------
    # Clean article only
    # --------------------------------------------------------

    type_article(
        page,
        editor,
        article
    )

    page.wait_for_timeout(
        2000
    )

    # --------------------------------------------------------
    # Publish button
    # --------------------------------------------------------

    publish_button = find_publish_button(
        page
    )

    if not publish_button:

        print(
            "✗ Publish button not found"
        )

        debug_page(
            page,
            "serey_publish_debug"
        )

        raise RuntimeError(
            "Serey publish button not found."
        )

    print(
        "✓ Publish button found"
    )

    try:

        publish_button.scroll_into_view_if_needed()

    except Exception:
        pass

    page.wait_for_timeout(
        1000
    )

    try:

        publish_button.click()

    except Exception:

        try:

            publish_button.evaluate(
                "(e) => e.click()"
            )

        except Exception as e:

            raise RuntimeError(
                f"Could not click publish: {e}"
            )

    print(
        "✓ Publish button clicked"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # Verify real published URL
    # --------------------------------------------------------

    verified, published_url = (
        verify_published_page(
            page,
            title
        )
    )

    if not verified:

        print()
        print(
            "✗ PUBLICATION VERIFICATION FAILED"
        )

        debug_page(
            page,
            "serey_publish_verify_debug"
        )

        raise RuntimeError(
            "Serey published URL "
            "could not be verified."
        )

    return published_url


# ============================================================
# CLEAN TEMP FILES
# ============================================================

def cleanup_images():

    print()
    print(
        "Cleaning temporary images..."
    )

    patterns = [
        "steem_thumbnail.*",
        "steem_image_*"
    ]

    removed = set()

    for pattern in patterns:

        for path in Path(".").glob(
            pattern
        ):

            if path in removed:
                continue

            try:

                path.unlink()

                removed.add(path)

                print(
                    f"Removed: "
                    f"{path.name}"
                )

            except Exception as e:

                print(
                    f"Could not remove "
                    f"{path.name}: {e}"
                )


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    cutoff = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            days=DAYS_TO_SYNC
        )
    )

    all_posts = []

    start_author = STEEM_USERNAME

    start_permlink = ""

    page_number = 1

    while True:

        print(
            f"Steem page "
            f"{page_number}: "
            f"requesting 100 results"
        )

        try:

            posts = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                [{
                    "tag": STEEM_USERNAME,
                    "limit": 100,
                    "start_author": start_author,
                    "start_permlink": start_permlink
                }]
            )

        except Exception as e:

            print(
                f"✗ Failed to get posts: "
                f"{e}"
            )

            break

        if not posts:
            break

        print(
            f"Steem page "
            f"{page_number}: "
            f"{len(posts)} results"
        )

        reached_cutoff = False

        for post in posts:

            if post.get(
                "author"
            ) != STEEM_USERNAME:

                continue

            created_string = post.get(
                "created"
            )

            try:

                created = datetime.fromisoformat(
                    created_string.replace(
                        "Z",
                        "+00:00"
                    )
                )

            except Exception:

                continue

            if created < cutoff:

                reached_cutoff = True

                continue

            post["_created_dt"] = created

            all_posts.append(
                post
            )

        if reached_cutoff:

            break

        if len(posts) < 100:

            break

        last = posts[-1]

        start_author = last.get(
            "author"
        )

        start_permlink = last.get(
            "permlink"
        )

        page_number += 1

        if page_number > 100:

            break

    all_posts.sort(
        key=lambda x: x["_created_dt"]
    )

    return all_posts


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=" * 60
    )

    print(
        "STEEM -> SEREY AUTO SYNC"
    )

    print(
        "=" * 60
    )

    print(
        "Mode:"
    )

    print(
        "• First image = thumbnail"
    )

    print(
        "• Body images = removed"
    )

    print(
        "• Steem HTML/Markdown = cleaned"
    )

    print(
        "• Published URL = REQUIRED"
    )

    print(
        "=" * 60
    )

    synced = load_synced()

    print(
        f"Previously synced: "
        f"{len(synced)}"
    )

    posts = get_posts()

    if not posts:

        print(
            "No posts found."
        )

        return

    print()
    print(
        f"Total posts in last "
        f"{DAYS_TO_SYNC} days: "
        f"{len(posts)}"
    )

    print(
        "Oldest:",
        posts[0].get("created"),
        f"{posts[0].get('author')}/"
        f"{posts[0].get('permlink')}"
    )

    print(
        "Newest:",
        posts[-1].get("created"),
        f"{posts[-1].get('author')}/"
        f"{posts[-1].get('permlink')}"
    )

    unsynced = []

    for post in posts:

        post_id = (
            f"{post.get('author')}/"
            f"{post.get('permlink')}"
        )

        if post_id not in synced:

            unsynced.append(
                post
            )

    print(
        f"Unsynced posts: "
        f"{len(unsynced)}"
    )

    if not unsynced:

        print(
            "✓ All posts already synced."
        )

        return

    selected = unsynced[
        :POSTS_PER_RUN
    ]

    print()
    print(
        f"Posts selected this run: "
        f"{len(selected)}"
    )

    for post in selected:

        print()
        print(
            "-" * 60
        )

        print(
            f"Selected: "
            f"{post.get('author')}/"
            f"{post.get('permlink')}"
        )

        print(
            f"Created: "
            f"{post.get('created')}"
        )

        print(
            f"Title: "
            f"{post.get('title')}"
        )

        print(
            "-" * 60
        )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000
            },
            locale="en-US"
        )

        page = context.new_page()

        try:

            if not login(page):

                raise RuntimeError(
                    "Serey login failed."
                )

            for post in selected:

                post_id = (
                    f"{post.get('author')}/"
                    f"{post.get('permlink')}"
                )

                print()
                print(
                    "=" * 60
                )

                print(
                    "Starting sync:"
                )

                print(
                    post_id
                )

                print(
                    "=" * 60
                )

                try:

                    published_url = publish_post(
                        page,
                        post
                    )

                    # ------------------------------------------------
                    # VERY IMPORTANT
                    # Only save after URL verification succeeds
                    # ------------------------------------------------

                    if published_url:

                        synced.add(
                            post_id
                        )

                        save_synced(
                            synced
                        )

                        print()
                        print(
                            "✓✓✓ SUCCESSFULLY SYNCED ✓✓✓"
                        )

                        print(
                            f"Steem post: "
                            f"{post_id}"
                        )

                        print(
                            "Serey published URL:"
                        )

                        print(
                            published_url
                        )

                        print(
                            f"Synced total: "
                            f"{len(synced)}"
                        )

                    else:

                        raise RuntimeError(
                            "No published URL returned."
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

                    print(
                        "⚠ This post will NOT "
                        "be added to synced_posts.json."
                    )

                    continue

        finally:

            cleanup_images()

            try:

                context.close()

            except Exception:
                pass

            try:

                browser.close()

            except Exception:
                pass

    print()
    print(
        "=" * 60
    )

    print(
        "RUN FINISHED"
    )

    print(
        "=" * 60
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
