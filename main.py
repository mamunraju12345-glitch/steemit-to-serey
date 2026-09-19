import os
import json
import re
import time
import requests
from datetime import datetime, timezone
from urllib.parse import urljoin
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

            print(
                f"RPC: {node}",
                flush=True
            )

            r = requests.post(
                node,
                json=payload,
                timeout=30
            )

            r.raise_for_status()

            data = r.json()

            if "error" in data:
                raise Exception(data["error"])

            return data["result"]

        except Exception as e:

            print(
                f"RPC failed: {e}",
                flush=True
            )

    raise Exception(
        "All Steem RPC nodes failed"
    )


# ============================================================
# DATE
# ============================================================

def parse_steem_date(value):

    if not value:
        return None

    try:

        value = value.strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

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
            f"Could not read synced file: {e}",
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
# IMAGE EXTRACTION
# ============================================================

def get_first_image(body, metadata):

    # 1. Markdown image
    try:

        m = re.search(
            r'!\[[^\]]*\]\(\s*(https?://[^)\s]+)',
            body,
            re.I
        )

        if m:
            return m.group(1)

    except Exception:
        pass

    # 2. HTML image
    try:

        m = re.search(
            r'<img[^>]+src=["\'](https?://[^"\']+)',
            body,
            re.I
        )

        if m:
            return m.group(1)

    except Exception:
        pass

    # 3. Steem metadata
    try:

        meta = json.loads(
            metadata or "{}"
        )

        images = meta.get(
            "image",
            []
        )

        if isinstance(images, list):

            for image in images:

                if (
                    isinstance(image, str)
                    and image.startswith("http")
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

    # Remove HTML comments
    body = re.sub(
        r'<!--.*?-->',
        '',
        body,
        flags=re.S
    )

    # Remove markdown images
    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    # Remove HTML images
    body = re.sub(
        r'<img[^>]*>',
        '',
        body,
        flags=re.I
    )

    # Remove image URLs
    body = re.sub(
        r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?',
        '',
        body,
        flags=re.I
    )

    # Markdown links -> visible text
    body = re.sub(
        r'\[([^\]]+)\]\([^)]+\)',
        r'\1',
        body
    )

    # HTML links -> visible text
    body = re.sub(
        r'<a[^>]*>(.*?)</a>',
        r'\1',
        body,
        flags=re.I | re.S
    )

    # Common block tags -> newline
    body = re.sub(
        r'</?(?:div|p|section|article|center|blockquote|li|ul|ol|h[1-6])[^>]*>',
        '\n',
        body,
        flags=re.I
    )

    # br
    body = re.sub(
        r'<br\s*/?>',
        '\n',
        body,
        flags=re.I
    )

    # Remove remaining HTML tags
    body = re.sub(
        r'<[^>]+>',
        '',
        body
    )

    # Markdown headings
    body = re.sub(
        r'^\s{0,3}#{1,6}\s*',
        '',
        body,
        flags=re.M
    )

    # Bold / italic / strike
    body = re.sub(
        r'(\*\*|__)(.*?)\1',
        r'\2',
        body,
        flags=re.S
    )

    body = re.sub(
        r'(?<!\*)\*([^*\n]+)\*(?!\*)',
        r'\1',
        body
    )

    body = re.sub(
        r'(?<!_)_([^_\n]+)_(?!_)',
        r'\1',
        body
    )

    body = re.sub(
        r'~~(.*?)~~',
        r'\1',
        body,
        flags=re.S
    )

    # Horizontal rules
    body = re.sub(
        r'^\s*([-*_]){3,}\s*$',
        '',
        body,
        flags=re.M
    )

    # Decode common HTML entities
    body = (
        body
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )

    # Remove excessive blank lines
    body = re.sub(
        r'\n[ \t]+',
        '\n',
        body
    )

    body = re.sub(
        r'\n{3,}',
        '\n\n',
        body
    )

    return body.strip()


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    print(
        f"Getting posts from @{STEEM_USERNAME}...",
        flush=True
    )

    cutoff = datetime.now(
        timezone.utc
    )

    from_date = cutoff.timestamp() - (
        DAYS_TO_SYNC * 86400
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None

    page_number = 0

    while len(posts) < 5000:

        page_number += 1

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:

            params["start_author"] = (
                start_author
            )

            params["start_permlink"] = (
                start_permlink
            )

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

        batch = (
            result[1:]
            if start_author
            else result
        )

        if not batch:
            break

        for p in batch:

            if p.get("author") != STEEM_USERNAME:
                continue

            author = p.get(
                "author",
                ""
            )

            permlink = p.get(
                "permlink",
                ""
            )

            created_raw = p.get(
                "created",
                ""
            )

            if not permlink:
                continue

            pid = (
                f"{author}/{permlink}"
            )

            if pid in seen:
                continue

            created = parse_steem_date(
                created_raw
            )

            if not created:
                continue

            if created.timestamp() < from_date:
                continue

            seen.add(pid)

            original_body = p.get(
                "body",
                ""
            )

            image = get_first_image(
                original_body,
                p.get(
                    "json_metadata",
                    "{}"
                )
            )

            body = clean_article(
                original_body
            )

            posts.append({
                "id": pid,
                "author": author,
                "permlink": permlink,
                "title": p.get(
                    "title",
                    ""
                ).strip(),
                "body": body,
                "image": image,
                "category": p.get(
                    "category",
                    ""
                ),
                "created": created_raw
            })

        last = result[-1]

        new_author = last.get(
            "author"
        )

        new_permlink = last.get(
            "permlink"
        )

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

        time.sleep(0.2)

    posts.sort(
        key=lambda x: (
            parse_steem_date(
                x["created"]
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        )
    )

    print(
        f"Total posts in last {DAYS_TO_SYNC} days: {len(posts)}",
        flush=True
    )

    if posts:

        print(
            f"Oldest: {posts[0]['created']} "
            f"{posts[0]['id']}",
            flush=True
        )

        print(
            f"Newest: {posts[-1]['created']} "
            f"{posts[-1]['id']}",
            flush=True
        )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if not url:
        return None

    try:

        print(
            f"Downloading thumbnail:\n{url}",
            flush=True
        )

        r = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/122.0 Safari/537.36"
                )
            }
        )

        r.raise_for_status()

        content_type = r.headers.get(
            "content-type",
            ""
        ).lower()

        if "image" not in content_type:

            print(
                f"Not an image: {content_type}",
                flush=True
            )

            return None

        if len(r.content) > 30 * 1024 * 1024:

            print(
                "Image is larger than 30 MB.",
                flush=True
            )

            return None

        with open(
            TEMP_IMAGE,
            "wb"
        ) as f:

            f.write(r.content)

        print(
            f"✓ Thumbnail downloaded: "
            f"{TEMP_IMAGE} ({len(r.content)} bytes)",
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

    login_buttons = page.locator(
        'a:has-text("Log in"),'
        'button:has-text("Log in"),'
        'a:has-text("Log In"),'
        'button:has-text("Log In")'
    )

    if login_buttons.count() == 0:

        print(
            "Login button not found. Assuming already logged in.",
            flush=True
        )

    else:

        login_buttons.first.click(
            force=True
        )

        page.wait_for_timeout(2500)

        username = page.locator(
            'input[placeholder*="Username" i]'
        ).first

        password = page.locator(
            'input[placeholder*="Private Key" i]'
        ).first

        if username.count() > 0:
            username.fill(SEREY_LOGIN)

        if password.count() > 0:
            password.fill(SEREY_PASSWORD)

        login_submit = page.locator(
            'button:has-text("Log in"),'
            'button:has-text("Log In")'
        )

        if login_submit.count() > 0:

            login_submit.last.click(
                force=True
            )

        page.wait_for_timeout(7000)

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


# ============================================================
# CROP MODAL
# ============================================================

def handle_crop_modal(page):

    print(
        "Checking thumbnail crop modal...",
        flush=True
    )

    for attempt in range(12):

        cropper = page.locator(
            '[data-testid="cropper"]'
        )

        modal = page.locator(
            '.ant-modal'
        )

        crop_visible = (
            cropper.count() > 0
            and cropper.first.is_visible()
        )

        modal_visible = (
            modal.count() > 0
            and modal.last.is_visible()
        )

        if not crop_visible and not modal_visible:

            if attempt == 0:
                print(
                    "No crop modal detected.",
                    flush=True
                )

            else:
                print(
                    "✓ Crop modal closed.",
                    flush=True
                )

            return True

        if attempt == 0:

            print(
                "✓ Image crop modal detected",
                flush=True
            )

            buttons = page.locator(
                '.ant-modal button'
            )

            print(
                f"Modal buttons found: {buttons.count()}",
                flush=True
            )

            for i in range(buttons.count()):

                b = buttons.nth(i)

                try:

                    if not b.is_visible():
                        continue

                    txt = b.inner_text().strip()

                    aria = (
                        b.get_attribute("aria-label")
                        or ""
                    )

                    title = (
                        b.get_attribute("title")
                        or ""
                    )

                    print(
                        f"Modal button {i}: "
                        f"text='{txt}' "
                        f"aria='{aria}' "
                        f"title='{title}'",
                        flush=True
                    )

                except Exception:
                    pass

        buttons = page.locator(
            '.ant-modal button'
        )

        # Prefer OK
        for i in range(buttons.count()):

            b = buttons.nth(i)

            try:

                if not b.is_visible():
                    continue

                txt = b.inner_text().strip().lower()

                aria = (
                    b.get_attribute(
                        "aria-label"
                    )
                    or ""
                ).lower()

                title = (
                    b.get_attribute(
                        "title"
                    )
                    or ""
                ).lower()

                combined = (
                    txt + " " +
                    aria + " " +
                    title
                )

                if txt in (
                    "ok",
                    "confirm",
                    "save",
                    "done",
                    "crop",
                    "upload"
                ):

                    print(
                        f"✓ Clicking crop confirmation: "
                        f"{txt}",
                        flush=True
                    )

                    b.click(
                        force=True
                    )

                    page.wait_for_timeout(
                        1200
                    )

                    break

            except Exception:
                continue

        else:

            # Keyboard fallback
            print(
                "No named confirmation found. "
                "Trying Enter...",
                flush=True
            )

            page.keyboard.press(
                "Enter"
            )

            page.wait_for_timeout(
                1000
            )

        # Check if modal disappeared
        cropper2 = page.locator(
            '[data-testid="cropper"]'
        )

        modal2 = page.locator(
            '.ant-modal'
        )

        still_open = False

        try:

            if (
                cropper2.count() > 0
                and cropper2.first.is_visible()
            ):
                still_open = True

        except Exception:
            pass

        try:

            if (
                modal2.count() > 0
                and modal2.last.is_visible()
            ):
                still_open = True

        except Exception:
            pass

        if not still_open:

            print(
                "✓ Crop modal closed",
                flush=True
            )

            print(
                "✓ Thumbnail crop confirmed",
                flush=True
            )

            return True

        page.wait_for_timeout(700)

    print(
        "❌ Crop modal could not be closed.",
        flush=True
    )

    return False


# ============================================================
# INSERT ARTICLE
# ============================================================

def insert_article(page, body):

    print(
        "Entering clean article...",
        flush=True
    )

    editor = page.locator(
        '[contenteditable="true"]'
    ).first

    if editor.count() == 0:

        raise Exception(
            "Serey content editor not found."
        )

    try:

        editor.click(
            timeout=5000
        )

    except Exception:

        editor.click(
            force=True
        )

    # Use JS because rich editors sometimes
    # ignore Playwright fill().
    page.evaluate(
        """
        (text) => {
            const el =
                document.querySelector(
                    '[contenteditable="true"]'
                );

            if (!el) {
                throw new Error(
                    'Content editor not found'
                );
            }

            el.focus();

            el.innerHTML = '';

            const lines = text.split('\\n');

            for (const line of lines) {

                const div =
                    document.createElement('div');

                if (line.trim() === '') {
                    div.innerHTML = '<br>';
                } else {
                    div.textContent = line;
                }

                el.appendChild(div);
            }

            el.dispatchEvent(
                new InputEvent(
                    'input',
                    {
                        bubbles: true,
                        inputType: 'insertText',
                        data: text
                    }
                )
            );

            el.dispatchEvent(
                new Event(
                    'change',
                    {
                        bubbles: true
                    }
                )
            );
        }
        """,
        body
    )

    page.wait_for_timeout(700)

    print(
        f"✓ Clean article inserted ({len(body)} characters)",
        flush=True
    )


# ============================================================
# FIND TITLE
# ============================================================

def fill_title(page, title):

    print(
        "Looking for Serey title field...",
        flush=True
    )

    selectors = [
        'textarea[placeholder="Enter title..."]',
        'input[placeholder="Enter title..."]',
        'textarea[placeholder*="title" i]',
        'input[placeholder*="title" i]'
    ]

    for selector in selectors:

        loc = page.locator(
            selector
        )

        print(
            f"Checking: {selector} -> {loc.count()}",
            flush=True
        )

        if loc.count() > 0:

            field = loc.first

            try:

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
                pass

    raise Exception(
        "Serey title field not found."
    )


# ============================================================
# UPLOAD THUMBNAIL
# ============================================================

def upload_thumbnail(page, image):

    if not image:
        return True

    print(
        "=" * 60
    )

    print(
        "Uploading FIRST IMAGE as thumbnail",
        flush=True
    )

    print(
        f"Thumbnail file: {image}",
        flush=True
    )

    inputs = page.locator(
        'input[type="file"]'
    )

    print(
        f"File inputs detected: {inputs.count()}",
        flush=True
    )

    if inputs.count() == 0:

        print(
            "❌ No image file input found.",
            flush=True
        )

        return False

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

    try:

        inputs.first.set_input_files(
            image
        )

        page.wait_for_timeout(2500)

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

    return handle_crop_modal(
        page
    )


# ============================================================
# PUBLISH BUTTON DEBUG
# ============================================================

def print_publish_buttons(page):

    buttons = page.locator(
        "button"
    )

    print(
        f"Publish search: {buttons.count()} buttons detected",
        flush=True
    )

    for i in range(
        buttons.count()
    ):

        b = buttons.nth(i)

        try:

            if not b.is_visible():
                continue

            txt = b.inner_text().strip()

            aria = (
                b.get_attribute(
                    "aria-label"
                )
                or ""
            )

            title = (
                b.get_attribute(
                    "title"
                )
                or ""
            )

            testid = (
                b.get_attribute(
                    "data-testid"
                )
                or ""
            )

            if (
                txt
                or aria
                or title
                or testid
            ):

                print(
                    f"Button {i}: "
                    f"text='{txt}' "
                    f"aria='{aria}' "
                    f"title='{title}' "
                    f"testid='{testid}'",
                    flush=True
                )

        except Exception:
            pass


# ============================================================
# FIRST PUBLISH
# ============================================================

def first_publish(page):

    print(
        "=" * 60
    )

    print(
        "Searching for FIRST Publish / Continue button...",
        flush=True
    )

    print_publish_buttons(
        page
    )

    # Exact visible Publish button
    publish_buttons = page.locator(
        'button:has-text("Publish")'
    )

    candidates = []

    for i in range(
        publish_buttons.count()
    ):

        b = publish_buttons.nth(i)

        try:

            if not b.is_visible():
                continue

            txt = b.inner_text().strip()

            if txt == "Publish":
                candidates.append(b)

        except Exception:
            continue

    if not candidates:

        raise Exception(
            "First Publish button not found."
        )

    # First Publish = first visible exact Publish
    button = candidates[0]

    print(
        "✓ Publish button found by text/role.",
        flush=True
    )

    print(
        "✓ Clicking first Publish button...",
        flush=True
    )

    button.click(
        force=True
    )

    page.wait_for_timeout(
        2500
    )

    print(
        "✓ FIRST PUBLISH CLICKED",
        flush=True
    )


# ============================================================
# CATEGORY
# ============================================================

def select_category(page, steem_category):

    print(
        f"Steem category: {steem_category}",
        flush=True
    )

    # Current Serey page may already have
    # Bengali Community selected.
    # Do not force a wrong Steem category.

    try:

        selector = page.get_by_text(
            "Select category",
            exact=True
        ).first

        if selector.count() == 0:

            print(
                "Category selection skipped.",
                flush=True
            )

            return False

        if not selector.is_visible():

            print(
                "Category selector not visible.",
                flush=True
            )

            return False

        selector.click(
            force=True
        )

        page.wait_for_timeout(
            800
        )

        options = page.locator(
            '[role="option"]'
        )

        for i in range(
            options.count()
        ):

            option = options.nth(i)

            try:

                if not option.is_visible():
                    continue

                txt = option.inner_text().strip()

                if (
                    txt.lower()
                    == steem_category.lower()
                ):

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

    except Exception as e:

        print(
            f"Category selection skipped: {e}",
            flush=True
        )

    return False


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(page):

    try:

        selector = page.get_by_text(
            "Select sub category",
            exact=True
        ).first

        if selector.count() == 0:

            print(
                "No Sub Category available.",
                flush=True
            )

            return

        if not selector.is_visible():

            print(
                "No Sub Category available.",
                flush=True
            )

            return

        selector.click(
            force=True
        )

        page.wait_for_timeout(
            700
        )

        options = page.locator(
            '[role="option"]'
        )

        for i in range(
            options.count()
        ):

            option = options.nth(i)

            try:

                if option.is_visible():

                    option.click(
                        force=True
                    )

                    print(
                        "✓ Sub Category selected.",
                        flush=True
                    )

                    return

            except Exception:
                continue

        print(
            "No Sub Category available.",
            flush=True
        )

    except Exception:

        print(
            "No Sub Category available.",
            flush=True
        )


# ============================================================
# EXTRACT SEREY URL FROM TEXT / HTML
# ============================================================

def extract_serey_url(text):

    if not text:
        return None

    patterns = [
        r'https?://(?:www\.)?(?:bengali\.)?serey\.io/authors/[^\s"\'<>]+',
        r'https?://(?:www\.)?serey\.io/authors/[^\s"\'<>]+'
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.I
        )

        if m:

            url = m.group(0)

            url = url.rstrip(
                ".,);]}>\"'"
            )

            return url

    return None


# ============================================================
# VALID SEREY POST URL
# ============================================================

def is_serey_post_url(url):

    if not url:
        return False

    return bool(
        re.match(
            r'^https?://(?:www\.)?(?:bengali\.)?serey\.io/authors/[^/]+/[^/?#]+',
            url,
            re.I
        )
    )


# ============================================================
# FIND URL IN PAGE
# ============================================================

def find_post_url_in_page(page):

    # 1. Current URL
    if is_serey_post_url(
        page.url
    ):
        return page.url

    # 2. Links on page
    try:

        links = page.locator(
            'a[href*="/authors/"]'
        )

        for i in range(
            links.count()
        ):

            a = links.nth(i)

            try:

                href = a.get_attribute(
                    "href"
                )

                if not href:
                    continue

                full = urljoin(
                    SEREY,
                    href
                )

                if is_serey_post_url(full):

                    return full

            except Exception:
                continue

    except Exception:
        pass

    # 3. Body text
    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=3000
        )

        url = extract_serey_url(
            text
        )

        if is_serey_post_url(url):
            return url

    except Exception:
        pass

    # 4. HTML source
    try:

        html = page.content()

        url = extract_serey_url(
            html
        )

        if is_serey_post_url(url):
            return url

    except Exception:
        pass

    return None


# ============================================================
# NETWORK RESPONSE EXTRACTION
# ============================================================

def response_url_candidates(response):

    found = []

    try:

        response_url = response.url

        url = extract_serey_url(
            response_url
        )

        if url:
            found.append(url)

    except Exception:
        pass

    try:

        content_type = (
            response.headers.get(
                "content-type",
                ""
            )
            .lower()
        )

        if (
            "json" not in content_type
            and "text" not in content_type
            and "javascript" not in content_type
        ):
            return found

        text = response.text()

        url = extract_serey_url(
            text
        )

        if url:
            found.append(url)

        # Look for JSON fields containing URL
        try:

            data = json.loads(
                text
            )

            dumped = json.dumps(
                data,
                ensure_ascii=False
            )

            url = extract_serey_url(
                dumped
            )

            if url:
                found.append(url)

        except Exception:
            pass

    except Exception:
        pass

    return found


# ============================================================
# VERIFY PUBLICATION
# ============================================================

def verify_publication(
    page,
    title,
    network_urls
):

    print(
        "=" * 60
    )

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    # --------------------------------------------------------
    # A. Network response URL
    # --------------------------------------------------------

    for url in network_urls:

        if is_serey_post_url(url):

            print(
                f"✓ PUBLISHED URL FOUND IN NETWORK:\n{url}",
                flush=True
            )

            return True, url

    # --------------------------------------------------------
    # B. Wait and inspect page
    # --------------------------------------------------------

    for attempt in range(
        1,
        13
    ):

        page.wait_for_timeout(
            2500
        )

        print(
            f"Verification attempt {attempt}:",
            flush=True
        )

        print(
            f"Current URL: {page.url}",
            flush=True
        )

        # Current URL
        if is_serey_post_url(
            page.url
        ):

            print(
                "✓ POST URL FOUND!",
                flush=True
            )

            return True, page.url

        # Page links / text / HTML
        found = find_post_url_in_page(
            page
        )

        if found:

            print(
                f"✓ PUBLISHED URL FOUND:\n{found}",
                flush=True
            )

            return True, found

        # Check page body for success/error
        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=3000
            )

            low = body_text.lower()

            # Print possible Serey messages
            keywords = [
                "success",
                "published",
                "post published",
                "error",
                "failed",
                "required"
            ]

            for word in keywords:

                if word in low:

                    print(
                        f"Page contains: {word}",
                        flush=True
                    )

        except Exception:
            pass

    # --------------------------------------------------------
    # C. Try activity/profile page
    # --------------------------------------------------------

    print(
        "No direct URL found. Checking profile activity...",
        flush=True
    )

    try:

        profile_url = (
            f"{SEREY}/authors/"
            f"{SEREY_LOGIN}/my-activity"
        )

        page.goto(
            profile_url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        page.wait_for_timeout(
            4000
        )

        found = find_post_url_in_page(
            page
        )

        if found:

            print(
                f"✓ POST FOUND FROM PROFILE:\n{found}",
                flush=True
            )

            return True, found

        # Search title in activity
        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        if title.lower() in body_text.lower():

            print(
                "✓ Post title found in profile activity.",
                flush=True
            )

            found = find_post_url_in_page(
                page
            )

            if found:
                return True, found

    except Exception as e:

        print(
            f"Profile verification failed: {e}",
            flush=True
        )

    print(
        "❌ Publication could not be verified.",
        flush=True
    )

    return False, None


# ============================================================
# DEBUG
# ============================================================

def save_debug(page):

    try:

        page.screenshot(
            path="serey_publish_debug.png",
            full_page=True
        )

        page_content = page.content()

        with open(
            "serey_publish_debug.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                page_content
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
# FINAL PUBLISH
# ============================================================

def final_publish(
    page,
    title
):

    print(
        "=" * 60
    )

    print(
        "Searching for FINAL Publish...",
        flush=True
    )

    print_publish_buttons(
        page
    )

    buttons = page.locator(
        "button"
    )

    publish_buttons = []

    for i in range(
        buttons.count()
    ):

        b = buttons.nth(i)

        try:

            if not b.is_visible():
                continue

            txt = b.inner_text().strip()

            if txt == "Publish":

                publish_buttons.append(
                    b
                )

        except Exception:
            continue

    if not publish_buttons:

        raise Exception(
            "FINAL Publish button not found."
        )

    print(
        "✓ FINAL Publish button found.",
        flush=True
    )

    # Last visible exact Publish is the confirmation
    final_button = publish_buttons[-1]

    # --------------------------------------------------------
    # Network listener
    # --------------------------------------------------------

    network_urls = []

    def capture_response(response):

        try:

            candidates = (
                response_url_candidates(
                    response
                )
            )

            for url in candidates:

                if url not in network_urls:

                    network_urls.append(
                        url
                    )

                    print(
                        f"✓ Network URL captured:\n{url}",
                        flush=True
                    )

        except Exception:
            pass

    page.on(
        "response",
        capture_response
    )

    # --------------------------------------------------------
    # Click FINAL PUBLISH
    # --------------------------------------------------------

    print(
        "✓ Clicking FINAL PUBLISH...",
        flush=True
    )

    final_button.click(
        force=True
    )

    print(
        "✓ FINAL PUBLISH CLICKED",
        flush=True
    )

    # --------------------------------------------------------
    # Give Serey time to publish
    # --------------------------------------------------------

    page.wait_for_timeout(
        5000
    )

    # --------------------------------------------------------
    # Check network immediately
    # --------------------------------------------------------

    for url in network_urls:

        if is_serey_post_url(url):

            print(
                f"✓ PUBLICATION CONFIRMED:\n{url}",
                flush=True
            )

            return True, url

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    success, url = verify_publication(
        page,
        title,
        network_urls
    )

    if success:

        return True, url

    # --------------------------------------------------------
    # Check for visible errors
    # --------------------------------------------------------

    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=3000
        )

        print(
            "SEREY PAGE TEXT AFTER PUBLISH:",
            flush=True
        )

        print(
            text[-4000:],
            flush=True
        )

    except Exception:
        pass

    save_debug(
        page
    )

    return False, None


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish(
    page,
    post
):

    print(
        "=" * 60
    )

    print(
        "Starting sync:",
        flush=True
    )

    print(
        post["id"],
        flush=True
    )

    print(
        "=" * 60
    )

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
        f"First image: {post['image']}",
        flush=True
    )

    # --------------------------------------------------------
    # WRITE PAGE
    # --------------------------------------------------------

    print(
        f"Write page: {NEW_POST}",
        flush=True
    )

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        3000
    )

    print(
        f"Current write URL: {page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    fill_title(
        page,
        post["title"]
    )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    insert_article(
        page,
        post["body"]
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

            raise Exception(
                "Thumbnail upload/crop failed."
            )

    else:

        print(
            "No thumbnail available.",
            flush=True
        )

    print(
        "✓ Ready to continue after thumbnail.",
        flush=True
    )

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    first_publish(
        page
    )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    select_category(
        page,
        post.get(
            "category",
            ""
        )
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

    success, published_url = final_publish(
        page,
        post["title"]
    )

    if success:

        print(
            "=" * 60
        )

        print(
            "✓✓✓ PUBLISHED SUCCESSFULLY ✓✓✓",
            flush=True
        )

        print(
            f"Published URL:\n{published_url}",
            flush=True
        )

        print(
            "=" * 60
        )

        return True, published_url

    print(
        "❌ Publication verification failed.",
        flush=True
    )

    return False, None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("STEEM -> SEREY AUTO SYNC")
    print("=" * 60)

    print(
        "• First image = thumbnail"
    )

    print(
        "• Thumbnail crop = automatic"
    )

    print(
        "• Body images = removed"
    )

    print(
        "• Steem HTML/Markdown = cleaned"
    )

    print(
        f"• Posts per run = {POSTS_PER_RUN}"
    )

    print(
        f"• Sync period = {DAYS_TO_SYNC} days"
    )

    print(
        "• Published URL = REQUIRED"
    )

    print(
        "• Date handling = UTC SAFE"
    )

    print("=" * 60)

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    posts = get_posts()

    new_posts = [
        p
        for p in posts
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

    for p in posts_to_run:

        print(
            f"Selected: {p['id']}",
            flush=True
        )

        print(
            f"Created: {p['created']}",
            flush=True
        )

        print(
            f"Title: {p['title']}",
            flush=True
        )

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
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            login(
                page
            )

            for post in posts_to_run:

                try:

                    success, published_url = publish(
                        page,
                        post
                    )

                    if success and published_url:

                        # ONLY NOW mark synced
                        synced.add(
                            post["id"]
                        )

                        save_synced(
                            synced
                        )

                        print(
                            f"✓ SAVED AS SYNCED: "
                            f"{post['id']}",
                            flush=True
                        )

                        print(
                            f"✓ SEREY URL: "
                            f"{published_url}",
                            flush=True
                        )

                    else:

                        print(
                            f"⚠ FAILED: "
                            f"{post['id']}",
                            flush=True
                        )

                        print(
                            "⚠ This post will NOT be added "
                            "to synced_posts.json.",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publish error: {e}",
                        flush=True
                    )

                    print(
                        "⚠ This post will NOT be added "
                        "to synced_posts.json.",
                        flush=True
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

    print("=" * 60)
    print("RUN FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
