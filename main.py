import os
import re
import json
import time
import html
import requests

from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    sync_playwright,
)


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = (
    os.environ.get("SEREY_LOGIN")
    or os.environ.get("SEREY_USERNAME")
    or ""
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()

SEREY = "https://bengali.serey.io"

NEW_POST = f"{SEREY}/write/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"

POSTS_PER_RUN = 1
DAYS_TO_SYNC = 365

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]


# ============================================================
# DATE
# ============================================================

def parse_steem_time(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

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
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(data, list):

            return set(
                str(x)
                for x in data
            )

        if isinstance(data, dict):

            return set(
                str(x)
                for x in data.keys()
            )

    except Exception as e:

        print(
            f"⚠ Could not read "
            f"{SYNC_FILE}: {e}"
        )

    return set()


def save_synced(synced):

    temp_file = (
        SYNC_FILE + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            sorted(synced),
            f,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(
        temp_file,
        SYNC_FILE,
    )


# ============================================================
# STEEM RPC
# ============================================================

def rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    last_error = None

    for node in STEEM_NODES:

        try:

            print(
                f"RPC: {node}"
            )

            response = requests.post(
                node,
                json=payload,
                timeout=30,
                headers={
                    "User-Agent":
                        "steemit-to-serey/1.0"
                },
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise RuntimeError(
                    data["error"]
                )

            print(
                f"✓ RPC success: {node}"
            )

            return data.get(
                "result"
            )

        except Exception as e:

            last_error = e

            print(
                f"⚠ RPC failed: "
                f"{node} -> {e}"
            )

    raise RuntimeError(
        f"All Steem RPC nodes failed: "
        f"{last_error}"
    )


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def get_first_image(
    body,
    metadata,
):

    # --------------------------------------------------------
    # JSON metadata
    # --------------------------------------------------------

    try:

        if isinstance(
            metadata,
            str,
        ):

            metadata = json.loads(
                metadata
            )

        if isinstance(
            metadata,
            dict,
        ):

            images = metadata.get(
                "image"
            )

            if isinstance(
                images,
                str,
            ):

                if images.startswith(
                    "http"
                ):
                    return images

            if isinstance(
                images,
                list,
            ):

                for image in images:

                    if (
                        isinstance(
                            image,
                            str,
                        )
                        and image.startswith(
                            "http"
                        )
                    ):
                        return image

    except Exception:
        pass

    # --------------------------------------------------------
    # HTML image
    # --------------------------------------------------------

    match = re.search(
        r'<img[^>]+src=["\']'
        r'(https?://[^"\']+)',
        body,
        re.IGNORECASE,
    )

    if match:
        return html.unescape(
            match.group(1)
        )

    # --------------------------------------------------------
    # Markdown image
    # --------------------------------------------------------

    match = re.search(
        r'!\[[^\]]*\]'
        r'\((https?://[^)\s]+)',
        body,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# CLEAN BODY
# ============================================================

def clean_post(
    body,
    metadata,
):

    if not body:

        return (
            "",
            get_first_image(
                "",
                metadata,
            ),
        )

    first_image = get_first_image(
        body,
        metadata,
    )

    text = body

    # HTML comments
    text = re.sub(
        r"<!--.*?-->",
        "",
        text,
        flags=re.DOTALL,
    )

    # HTML images
    text = re.sub(
        r"<img\b[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Markdown images
    text = re.sub(
        r"!\[[^\]]*\]"
        r"\([^)]+\)",
        "",
        text,
    )

    # HTML block tags
    text = re.sub(
        r"</?(p|div|br|li|blockquote|"
        r"h1|h2|h3|h4|h5|h6)"
        r"[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    # HTML links
    text = re.sub(
        r'<a\b[^>]*>'
        r'(.*?)'
        r'</a>',
        r"\1",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    # Remaining HTML
    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    # Markdown links
    text = re.sub(
        r"\[([^\]]+)\]"
        r"\([^)]+\)",
        r"\1",
        text,
    )

    # Markdown headings
    text = re.sub(
        r"(?m)^\s{0,3}"
        r"#{1,6}\s*",
        "",
        text,
    )

    # Bold
    text = re.sub(
        r"(\*\*|__)"
        r"(.*?)"
        r"\1",
        r"\2",
        text,
        flags=re.DOTALL,
    )

    # Italic
    text = re.sub(
        r"(?<!\*)"
        r"\*([^*\n]+)"
        r"\*(?!\*)",
        r"\1",
        text,
    )

    text = re.sub(
        r"(?<!_)"
        r"_([^_\n]+)"
        r"_(?!_)",
        r"\1",
        text,
    )

    # Strike
    text = re.sub(
        r"~~(.*?)~~",
        r"\1",
        text,
        flags=re.DOTALL,
    )

    # Code markers
    text = re.sub(
        r"`{1,3}",
        "",
        text,
    )

    # Blockquotes
    text = re.sub(
        r"(?m)^\s*>\s?",
        "",
        text,
    )

    # Image URLs
    text = re.sub(
        r"https?://\S+"
        r"\.(?:jpg|jpeg|png|gif|webp)"
        r"(?:\?\S*)?",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # HTML entities
    text = html.unescape(
        text
    )

    # Normalize line endings
    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    # Remove trailing spaces
    text = re.sub(
        r"[ \t]+\n",
        "\n",
        text,
    )

    # Maximum 2 blank lines
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return (
        text.strip(),
        first_image,
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

    print(
        f"Sync cutoff: "
        f"{cutoff.isoformat()}"
    )

    posts = []

    start_author = ""
    start_permlink = ""

    page_number = 0

    while True:

        page_number += 1

        params = [
            {
                "tag": STEEM_USERNAME,
                "limit": 100,
                "start_author":
                    start_author,
                "start_permlink":
                    start_permlink,
            }
        ]

        try:

            result = rpc(
                "condenser_api."
                "get_discussions_by_blog",
                params,
            )

        except Exception as e:

            print(
                f"❌ Could not get "
                f"Steem posts: {e}"
            )

            break

        if not result:
            break

        print(
            f"Steem page "
            f"{page_number}: "
            f"{len(result)} results"
        )

        reached_cutoff = False

        for post in result:

            created = parse_steem_time(
                post.get(
                    "created"
                )
            )

            if not created:
                continue

            if created < cutoff:

                reached_cutoff = True

                continue

            author = post.get(
                "author",
                "",
            )

            permlink = post.get(
                "permlink",
                "",
            )

            if not author or not permlink:
                continue

            metadata = post.get(
                "json_metadata",
                {},
            )

            body, image = clean_post(
                post.get(
                    "body",
                    "",
                ),
                metadata,
            )

            posts.append(
                {
                    "author":
                        author,

                    "permlink":
                        permlink,

                    "title":
                        post.get(
                            "title",
                            "",
                        ).strip(),

                    "body":
                        body,

                    "image":
                        image,

                    "created":
                        created,

                    "category":
                        post.get(
                            "category",
                            "",
                        ),
                }
            )

        last_post = result[-1]

        last_created = parse_steem_time(
            last_post.get(
                "created"
            )
        )

        if reached_cutoff:
            break

        if (
            last_created
            and last_created < cutoff
        ):
            break

        new_author = last_post.get(
            "author",
            "",
        )

        new_permlink = last_post.get(
            "permlink",
            "",
        )

        if (
            new_author == start_author
            and
            new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

    posts.sort(
        key=lambda x:
            x["created"]
    )

    print()

    print(
        f"Total posts in last "
        f"{DAYS_TO_SYNC} days: "
        f"{len(posts)}"
    )

    if posts:

        print(
            f"Oldest: "
            f"{posts[0]['created'].isoformat()} "
            f"{posts[0]['author']}/"
            f"{posts[0]['permlink']}"
        )

        print(
            f"Newest: "
            f"{posts[-1]['created'].isoformat()} "
            f"{posts[-1]['author']}/"
            f"{posts[-1]['permlink']}"
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
            "Downloading thumbnail..."
        )

        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent":
                    "Mozilla/5.0"
            },
        )

        response.raise_for_status()

        with open(
            TEMP_IMAGE,
            "wb",
        ) as f:

            f.write(
                response.content
            )

        size = os.path.getsize(
            TEMP_IMAGE
        )

        print(
            f"✓ Thumbnail downloaded: "
            f"{TEMP_IMAGE} "
            f"({size} bytes)"
        )

        return TEMP_IMAGE

    except Exception as e:

        print(
            f"⚠ Thumbnail download "
            f"failed: {e}"
        )

        return None


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
        timeout=60000,
    )

    page.wait_for_timeout(
        3000
    )

    username_input = None
    password_input = None

    username_selectors = [
        'input[placeholder*="Username"]',
        'input[placeholder*="username"]',
        'input[name="username"]',
        'input[type="text"]',
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

                if item.is_visible():

                    username_input = item
                    break

            if username_input:
                break

        except Exception:
            pass

    password_selectors = [
        'input[placeholder*="Private"]',
        'input[placeholder*="private"]',
        'input[placeholder*="Password"]',
        'input[placeholder*="password"]',
        'input[type="password"]',
    ]

    for selector in password_selectors:

        try:

            loc = page.locator(
                selector
            )

            for i in range(
                loc.count()
            ):

                item = loc.nth(i)

                if item.is_visible():

                    password_input = item
                    break

            if password_input:
                break

        except Exception:
            pass

    if (
        username_input
        and password_input
    ):

        username_input.fill(
            SEREY_LOGIN
        )

        password_input.fill(
            SEREY_PASSWORD
        )

        buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"^(Log in|Login|Sign in)$",
                re.IGNORECASE,
            ),
        )

        clicked = False

        for i in range(
            buttons.count()
        ):

            try:

                button = buttons.nth(i)

                if button.is_visible():

                    button.click(
                        force=True
                    )

                    clicked = True
                    break

            except Exception:
                pass

        if not clicked:

            print(
                "⚠ Login button "
                "not found."
            )

        page.wait_for_timeout(
            5000
        )

    else:

        print(
            "✓ Login fields not visible; "
            "checking whether already "
            "logged in."
        )

    print(
        f"After login URL: "
        f"{page.url}"
    )

    body_text = ""

    try:

        body_text = (
            page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )
        )

    except Exception:
        pass

    if (
        SEREY_LOGIN.lower()
        in body_text.lower()
        or
        "Write a Post"
        in body_text
        or
        "Write"
        in body_text
    ):

        print(
            "✓ LOGGED INTO SEREY SUCCESSFULLY!"
        )

        return True

    if "/login" not in page.url.lower():

        print(
            "✓ LOGGED INTO SEREY SUCCESSFULLY!"
        )

        return True

    print(
        "❌ SEREY LOGIN FAILED"
    )

    return False


# ============================================================
# CLEANUP MODALS
# ============================================================

def wait_for_all_modals_to_close(
    page,
    timeout=15000,
):

    start = time.time()

    while (
        time.time() - start
        < timeout / 1000
    ):

        crop_visible = 0
        modal_visible = 0

        try:

            crop_visible = page.locator(
                '[data-testid="cropper"]:visible'
            ).count()

        except Exception:
            pass

        try:

            modal_visible = page.locator(
                ".ant-modal-wrap:visible"
            ).count()

        except Exception:
            pass

        if (
            crop_visible == 0
            and
            modal_visible == 0
        ):

            # Allow React/Ant Design
            # animation to finish.
            page.wait_for_timeout(
                800
            )

            return True

        page.wait_for_timeout(
            300
        )

    return False


# ============================================================
# CROP MODAL
# ============================================================

def handle_crop_modal(page):

    print(
        "Checking thumbnail crop modal..."
    )

    try:

        page.wait_for_timeout(
            1000
        )

        cropper = page.locator(
            '[data-testid="cropper"]'
        )

        if cropper.count() == 0:

            print(
                "No crop modal detected."
            )

            return True

        if not cropper.first.is_visible():

            print(
                "No visible crop modal."
            )

            return True

        print(
            "✓ Image crop modal detected"
        )

        ok_buttons = page.get_by_role(
            "button",
            name="OK",
            exact=True,
        )

        target = None

        for i in range(
            ok_buttons.count()
        ):

            try:

                button = ok_buttons.nth(i)

                if button.is_visible():

                    target = button
                    break

            except Exception:
                pass

        if not target:

            print(
                "❌ Crop OK button "
                "not found."
            )

            return False

        print(
            "✓ Clicking crop confirmation: OK"
        )

        target.click(
            force=True
        )

        # Wait until cropper disappears
        try:

            cropper.first.wait_for(
                state="hidden",
                timeout=15000,
            )

        except Exception:
            pass

        # Wait until Ant modal wrapper
        # disappears.
        wait_for_all_modals_to_close(
            page,
            timeout=15000,
        )

        # Extra React rendering time
        page.wait_for_timeout(
            1500
        )

        # Final check
        crop_visible = page.locator(
            '[data-testid="cropper"]:visible'
        ).count()

        modal_visible = page.locator(
            ".ant-modal-wrap:visible"
        ).count()

        if (
            crop_visible == 0
            and
            modal_visible == 0
        ):

            print(
                "✓ Crop modal closed"
            )

            print(
                "✓ Thumbnail crop confirmed"
            )

            print(
                "✓ Ready to continue "
                "after thumbnail."
            )

            return True

        # If something invisible-looking
        # remains, force close only if
        # it is not the cropper itself.
        print(
            "⚠ Modal wrapper still detected; "
            "performing final cleanup."
        )

        try:

            page.keyboard.press(
                "Escape"
            )

        except Exception:
            pass

        page.wait_for_timeout(
            1000
        )

        return True

    except Exception as e:

        print(
            f"❌ Crop modal handling "
            f"failed: {e}"
        )

        return False


# ============================================================
# FIND PUBLISH BUTTONS
# ============================================================

def get_visible_publish_buttons(
    page
):

    result = []

    try:

        buttons = page.get_by_role(
            "button",
            name="Publish",
            exact=True,
        )

        for i in range(
            buttons.count()
        ):

            try:

                button = buttons.nth(i)

                if button.is_visible():

                    result.append(
                        button
                    )

            except Exception:
                pass

    except Exception:
        pass

    return result


# ============================================================
# FIRST PUBLISH
# ============================================================

def click_first_publish(page):

    print(
        "============================================================"
    )

    print(
        "Searching for FIRST "
        "Publish / Continue button..."
    )

    # Absolutely ensure crop modal
    # has disappeared.
    wait_for_all_modals_to_close(
        page,
        timeout=10000,
    )

    page.wait_for_timeout(
        1500
    )

    buttons = (
        get_visible_publish_buttons(
            page
        )
    )

    print(
        f"Publish buttons detected: "
        f"{len(buttons)}"
    )

    if not buttons:

        print(
            "❌ Publish button not found."
        )

        return False

    button = buttons[0]

    try:

        print(
            "✓ Publish button found "
            "by text/role."
        )

        # Scroll into view
        button.scroll_into_view_if_needed()

        page.wait_for_timeout(
            1000
        )

        print(
            "✓ Clicking first Publish button..."
        )

        # ----------------------------------------------------
        # NORMAL CLICK FIRST
        # ----------------------------------------------------

        try:

            button.click(
                timeout=10000
            )

        except Exception as normal_error:

            print(
                "⚠ Normal click blocked."
            )

            print(
                "⚠ Performing final "
                "modal cleanup..."
            )

            wait_for_all_modals_to_close(
                page,
                timeout=5000,
            )

            page.wait_for_timeout(
                1000
            )

            button.scroll_into_view_if_needed()

            page.wait_for_timeout(
                500
            )

            # ------------------------------------------------
            # FORCE CLICK FALLBACK
            # ------------------------------------------------

            button.click(
                force=True,
                timeout=10000,
            )

        page.wait_for_timeout(
            2500
        )

        print(
            "✓ FIRST PUBLISH CLICKED"
        )

        return True

    except Exception as e:

        print(
            f"❌ First Publish click "
            f"failed: {e}"
        )

        try:

            page.screenshot(
                path=
                    "publish_click_failed.png",
                full_page=True,
            )

        except Exception:
            pass

        return False


# ============================================================
# FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    print(
        "============================================================"
    )

    print(
        "Searching for FINAL Publish..."
    )

    for attempt in range(10):

        buttons = (
            get_visible_publish_buttons(
                page
            )
        )

        print(
            f"Final Publish search "
            f"attempt {attempt + 1}: "
            f"{len(buttons)} buttons"
        )

        if buttons:

            target = buttons[-1]

            try:

                if target.is_enabled():

                    print(
                        "✓ FINAL Publish "
                        "button found."
                    )

                    print(
                        "✓ Clicking FINAL PUBLISH..."
                    )

                    try:

                        target.click(
                            timeout=10000
                        )

                    except Exception:

                        print(
                            "⚠ Normal final "
                            "click blocked; "
                            "using force click."
                        )

                        target.click(
                            force=True,
                            timeout=10000,
                        )

                    print(
                        "✓ FINAL PUBLISH CLICKED"
                    )

                    return True

            except Exception as e:

                print(
                    f"⚠ Final Publish "
                    f"click error: {e}"
                )

        page.wait_for_timeout(
            1000
        )

    print(
        "❌ FINAL Publish button "
        "not found."
    )

    return False


# ============================================================
# NETWORK CAPTURE
# ============================================================

class NetworkCapture:

    def __init__(self):

        self.responses = []
        self.requests = []

    def request(
        self,
        request,
    ):

        try:

            if request.resource_type in (
                "xhr",
                "fetch",
            ):

                self.requests.append(
                    {
                        "method":
                            request.method,

                        "url":
                            request.url,
                    }
                )

        except Exception:
            pass

    def response(
        self,
        response,
    ):

        try:

            if (
                response.request
                .resource_type
                not in (
                    "xhr",
                    "fetch",
                )
            ):
                return

            text = ""

            try:

                text = response.text()

            except Exception:
                pass

            self.responses.append(
                {
                    "url":
                        response.url,

                    "status":
                        response.status,

                    "text":
                        text[:20000],
                }
            )

        except Exception:
            pass


# ============================================================
# URL NORMALIZATION
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = html.unescape(
        url
    )

    url = url.replace(
        "\\/",
        "/",
    )

    return url.strip(
        " \t\r\n\"'<>.,);"
    )


# ============================================================
# REAL POST URL CHECK
# ============================================================

def is_real_post_url(url):

    """
    IMPORTANT:

    /authors/USER/my-activity
        = NOT a post

    /authors/USER/POST_ID
        = possible post
    """

    if not url:
        return False

    url = normalize_url(
        url
    )

    try:

        parsed = urlparse(
            url
        )

        host = (
            parsed.netloc
            .lower()
        )

        if not (
            host == "serey.io"
            or
            host == "www.serey.io"
            or
            host.endswith(
                ".serey.io"
            )
        ):
            return False

        path = (
            parsed.path
            .rstrip("/")
        )

        match = re.match(
            r"^/authors/"
            r"([^/]+)/"
            r"([^/]+)$",
            path,
            re.IGNORECASE,
        )

        if not match:
            return False

        username = match.group(
            1
        )

        post_id = match.group(
            2
        )

        # ----------------------------------------------------
        # NEVER ACCEPT THESE AS POSTS
        # ----------------------------------------------------

        if post_id.lower() in {
            "my-activity",
            "activity",
            "profile",
            "posts",
            "followers",
            "following",
        }:

            return False

        # Correct account only
        if SEREY_LOGIN:

            if (
                username.lower()
                !=
                SEREY_LOGIN.lower()
            ):

                return False

        if len(post_id) < 4:
            return False

        return True

    except Exception:
        return False


# ============================================================
# EXTRACT POST URL FROM TEXT
# ============================================================

def extract_post_urls(text):

    if not text:
        return []

    text = (
        text
        .replace(
            "\\/",
            "/",
        )
        .replace(
            "&quot;",
            '"',
        )
    )

    found = []

    absolute_pattern = re.compile(
        r'https?://'
        r'(?:[A-Za-z0-9-]+\.)?'
        r'serey\.io'
        r'/authors/'
        r'[A-Za-z0-9._~!$&()*+,;=:@%-]+/'
        r'[A-Za-z0-9._~!$&()*+,;=:@%-]+',
        re.IGNORECASE,
    )

    for match in (
        absolute_pattern.findall(
            text
        )
    ):

        url = normalize_url(
            match
        )

        if is_real_post_url(
            url
        ):

            if url not in found:
                found.append(
                    url
                )

    relative_pattern = re.compile(
        r'/authors/'
        r'[A-Za-z0-9._~!$&()*+,;=:@%-]+/'
        r'[A-Za-z0-9._~!$&()*+,;=:@%-]+',
        re.IGNORECASE,
    )

    for match in (
        relative_pattern.findall(
            text
        )
    ):

        url = urljoin(
            SEREY,
            match,
        )

        if is_real_post_url(
            url
        ):

            if url not in found:
                found.append(
                    url
                )

    return found


# ============================================================
# JSON URL EXTRACTION
# ============================================================

def collect_urls_from_json(
    value
):

    found = []

    if isinstance(
        value,
        dict,
    ):

        for key, item in (
            value.items()
        ):

            key_lower = str(
                key
            ).lower()

            if isinstance(
                item,
                str,
            ):

                if (
                    "url"
                    in key_lower
                    or
                    "link"
                    in key_lower
                    or
                    "href"
                    in key_lower
                    or
                    "permalink"
                    in key_lower
                    or
                    "permlink"
                    in key_lower
                ):

                    found.extend(
                        extract_post_urls(
                            item
                        )
                    )

                if key_lower in (
                    "permlink",
                    "slug",
                ):

                    candidate = urljoin(
                        SEREY,
                        f"/authors/"
                        f"{SEREY_LOGIN}/"
                        f"{item}",
                    )

                    if is_real_post_url(
                        candidate
                    ):

                        found.append(
                            candidate
                        )

            else:

                found.extend(
                    collect_urls_from_json(
                        item
                    )
                )

    elif isinstance(
        value,
        list,
    ):

        for item in value:

            found.extend(
                collect_urls_from_json(
                    item
                )
            )

    return found


# ============================================================
# NETWORK POST URL
# ============================================================

def find_url_in_network(
    capture
):

    candidates = []

    for item in (
        capture.responses
    ):

        text = item.get(
            "text",
            "",
        )

        candidates.extend(
            extract_post_urls(
                text
            )
        )

        if text:

            try:

                data = json.loads(
                    text
                )

                candidates.extend(
                    collect_urls_from_json(
                        data
                    )
                )

            except Exception:
                pass

    unique = []

    for url in candidates:

        url = normalize_url(
            url
        )

        if (
            is_real_post_url(
                url
            )
            and
            url not in unique
        ):

            unique.append(
                url
            )

    return unique


# ============================================================
# FIND POST LINK ON PAGE
# ============================================================

def find_post_link_on_page(
    page,
    title,
):

    candidates = []

    try:

        links = page.locator(
            "a"
        )

        for i in range(
            links.count()
        ):

            try:

                link = links.nth(i)

                if not link.is_visible():
                    continue

                href = link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                url = urljoin(
                    page.url,
                    href,
                )

                # THIS rejects my-activity
                if not is_real_post_url(
                    url
                ):
                    continue

                try:

                    link_text = (
                        link.inner_text()
                        .strip()
                    )

                except Exception:

                    link_text = ""

                candidates.append(
                    (
                        url,
                        link_text,
                    )
                )

            except Exception:
                pass

    except Exception:
        pass

    title_clean = re.sub(
        r"\s+",
        " ",
        title.strip(),
    ).lower()

    # Exact/partial title
    for url, link_text in (
        candidates
    ):

        link_clean = re.sub(
            r"\s+",
            " ",
            link_text.strip(),
        ).lower()

        if (
            title_clean
            and
            (
                title_clean
                == link_clean
                or
                title_clean
                in link_clean
                or
                link_clean
                in title_clean
            )
        ):

            print(
                f"✓ POST LINK FOUND BY TITLE: "
                f"{url}"
            )

            return url

    # If exactly one REAL post link exists
    if len(candidates) == 1:

        print(
            "✓ One real post link found."
        )

        return candidates[0][0]

    return None


# ============================================================
# VERIFY REAL POST PAGE
# ============================================================

def verify_real_post_page(
    page,
    url,
    title,
):

    # First safety check
    if not is_real_post_url(
        url
    ):

        print(
            f"❌ REJECTED URL: "
            f"{url}"
        )

        return False

    print(
        f"Checking real post URL: "
        f"{url}"
    )

    for attempt in range(
        1,
        6,
    ):

        try:

            response = page.goto(
                url,
                wait_until=
                    "domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(
                3000
            )

            status = (
                response.status
                if response
                else None
            )

            print(
                f"Post verification "
                f"attempt {attempt}: "
                f"HTTP {status}"
            )

            current = normalize_url(
                page.url
            )

            # NEVER accept redirect to
            # my-activity
            if not is_real_post_url(
                current
            ):

                print(
                    "⚠ Redirected to "
                    "non-post URL."
                )

                time.sleep(2)

                continue

            body_text = ""

            try:

                body_text = (
                    page.locator(
                        "body"
                    ).inner_text(
                        timeout=10000
                    )
                )

            except Exception:
                pass

            normalized_body = re.sub(
                r"\s+",
                " ",
                body_text,
            ).strip().lower()

            normalized_title = re.sub(
                r"\s+",
                " ",
                title,
            ).strip().lower()

            if (
                normalized_title
                and
                normalized_title
                in normalized_body
            ):

                print(
                    "✓ POST TITLE VERIFIED "
                    "ON REAL POST PAGE"
                )

                print(
                    f"✓ VERIFIED PUBLISHED URL: "
                    f"{current}"
                )

                return current

            print(
                "⚠ Real post URL opened, "
                "but title not visible yet."
            )

        except Exception as e:

            print(
                f"⚠ Verification error: "
                f"{e}"
            )

        time.sleep(3)

    return False


# ============================================================
# ACTIVITY SEARCH
# ============================================================

def search_activity_for_post(
    page,
    title,
):

    activity_urls = [
        (
            f"{SEREY}/authors/"
            f"{SEREY_LOGIN}/my-activity"
        ),
        (
            f"{SEREY}/authors/"
            f"{SEREY_LOGIN}"
        ),
    ]

    for activity_url in (
        activity_urls
    ):

        print(
            f"Checking profile/activity: "
            f"{activity_url}"
        )

        try:

            page.goto(
                activity_url,
                wait_until=
                    "domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(
                5000
            )

            # IMPORTANT:
            # We search activity only to
            # FIND a real post link.
            #
            # We NEVER return activity_url.
            candidate = (
                find_post_link_on_page(
                    page,
                    title,
                )
            )

            if candidate:

                verified = (
                    verify_real_post_page(
                        page,
                        candidate,
                        title,
                    )
                )

                if verified:
                    return verified

        except Exception as e:

            print(
                f"⚠ Activity search "
                f"error: {e}"
            )

    return None


# ============================================================
# NETWORK DIAGNOSTICS
# ============================================================

def print_network_errors(
    capture
):

    print()
    print(
        "============================================================"
    )
    print(
        "SEREY NETWORK DIAGNOSTICS"
    )
    print(
        "============================================================"
    )

    if not capture.responses:

        print(
            "No XHR/fetch responses captured."
        )

        return

    printed = 0

    for item in (
        capture.responses
    ):

        status = item.get(
            "status"
        )

        url = item.get(
            "url",
            "",
        )

        text = item.get(
            "text",
            "",
        )

        if (
            status is not None
            and
            status >= 400
        ):

            print(
                f"HTTP {status}: "
                f"{url}"
            )

            if text:

                cleaned = re.sub(
                    r"\s+",
                    " ",
                    text,
                )

                print(
                    f"Response: "
                    f"{cleaned[:1500]}"
                )

            printed += 1

        elif text:

            lower = text.lower()

            if any(
                word in lower
                for word in [
                    '"error"',
                    '"errors"',
                    '"message"',
                    '"failed"',
                    '"failure"',
                    '"reason"',
                ]
            ):

                print(
                    f"Response {status}: "
                    f"{url}"
                )

                cleaned = re.sub(
                    r"\s+",
                    " ",
                    text,
                )

                print(
                    f"Response: "
                    f"{cleaned[:1500]}"
                )

                printed += 1

        if printed >= 10:
            break

    if printed == 0:

        print(
            "No obvious network "
            "error response found."
        )


# ============================================================
# VISIBLE MESSAGES
# ============================================================

def print_visible_errors(
    page
):

    print()
    print(
        "============================================================"
    )
    print(
        "VISIBLE SEREY MESSAGES"
    )
    print(
        "============================================================"
    )

    selectors = [
        '[role="alert"]',
        '.ant-message',
        '.ant-notification',
        '.ant-modal-body',
        '[class*="toast"]',
        '[class*="Toast"]',
        '[class*="notification"]',
        '[class*="alert"]',
    ]

    found = set()

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            for i in range(
                min(
                    loc.count(),
                    10,
                )
            ):

                try:

                    item = loc.nth(i)

                    if not item.is_visible():
                        continue

                    value = (
                        item.inner_text()
                        .strip()
                    )

                    value = re.sub(
                        r"\s+",
                        " ",
                        value,
                    )

                    if (
                        value
                        and
                        value not in found
                    ):

                        found.add(
                            value
                        )

                        print(
                            f"Message: "
                            f"{value[:1000]}"
                        )

                except Exception:
                    pass

        except Exception:
            pass

    if not found:

        print(
            "No visible message detected."
        )


# ============================================================
# DEBUG FILES
# ============================================================

def save_debug(
    page,
    capture,
):

    try:

        page.screenshot(
            path=
                "serey_publish_debug.png",
            full_page=True,
        )

        with open(
            "serey_publish_debug.html",
            "w",
            encoding="utf-8",
        ) as f:

            f.write(
                page.content()
            )

        network_data = []

        for item in (
            capture.responses
        ):

            network_data.append(
                {
                    "url":
                        item.get(
                            "url"
                        ),

                    "status":
                        item.get(
                            "status"
                        ),

                    "response_preview":
                        item.get(
                            "text",
                            "",
                        )[:3000],
                }
            )

        with open(
            "serey_network_debug.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                network_data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(
            "✓ Debug files saved."
        )

    except Exception as e:

        print(
            f"⚠ Could not save "
            f"debug files: {e}"
        )


# ============================================================
# PUBLISH POST
# ============================================================

def publish_post(
    page,
    post,
):

    title = post["title"]
    body = post["body"]
    image_url = post["image"]

    print()
    print(
        "============================================================"
    )
    print(
        f"Publishing: "
        f"{post['author']}/"
        f"{post['permlink']}"
    )
    print(
        f"Title: {title}"
    )
    print(
        "============================================================"
    )

    # --------------------------------------------------------
    # OPEN EDITOR
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until=
            "domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(
        3000
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_selector = (
        'textarea[placeholder="Enter title..."]'
    )

    try:

        title_field = page.locator(
            title_selector
        ).first

        title_field.wait_for(
            state="visible",
            timeout=15000,
        )

        print(
            f"Title field found: "
            f"{title_selector}"
        )

        title_field.fill(
            title
        )

        print(
            "✓ Title filled"
        )

    except Exception as e:

        print(
            f"❌ Title field failed: "
            f"{e}"
        )

        return None

    # --------------------------------------------------------
    # THUMBNAIL
    # --------------------------------------------------------

    if image_url:

        image_file = download_image(
            image_url
        )

        if image_file:

            try:

                print(
                    "Uploading FIRST IMAGE "
                    "as thumbnail"
                )

                inputs = page.locator(
                    'input[type="file"]'
                )

                print(
                    f"File inputs detected: "
                    f"{inputs.count()}"
                )

                uploaded = False

                for i in range(
                    inputs.count()
                ):

                    try:

                        inp = inputs.nth(
                            i
                        )

                        accept = (
                            inp.get_attribute(
                                "accept"
                            )
                            or ""
                        )

                        name = (
                            inp.get_attribute(
                                "name"
                            )
                            or ""
                        )

                        print(
                            f"File input {i}: "
                            f"accept={accept} "
                            f"name={name}"
                        )

                        inp.set_input_files(
                            image_file
                        )

                        uploaded = True

                        break

                    except Exception:
                        pass

                if not uploaded:

                    print(
                        "⚠ Thumbnail upload "
                        "failed."
                    )

                else:

                    print(
                        "✓ Thumbnail uploaded "
                        "using single image input"
                    )

                    if not handle_crop_modal(
                        page
                    ):

                        print(
                            "❌ Thumbnail crop failed."
                        )

                        return None

            except Exception as e:

                print(
                    f"⚠ Thumbnail upload "
                    f"error: {e}"
                )

    # --------------------------------------------------------
    # EDITOR
    # --------------------------------------------------------

    try:

        editor = page.locator(
            '[contenteditable="true"]'
        ).first

        editor.wait_for(
            state="visible",
            timeout=15000,
        )

        print(
            "✓ Editor found: "
            "[contenteditable=\"true\"]"
        )

        editor.fill(
            body
        )

        print(
            f"✓ Clean article inserted "
            f"({len(body)} characters)"
        )

    except Exception as e:

        print(
            f"❌ Editor failed: "
            f"{e}"
        )

        return None

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    if not click_first_publish(
        page
    ):

        return None

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    print(
        f"Steem category: "
        f"{post.get('category', 'hive-129948')}"
    )

    print(
        "Category selection skipped."
    )

    print(
        "No Sub Category available."
    )

    # --------------------------------------------------------
    # START NETWORK CAPTURE
    # --------------------------------------------------------

    capture = NetworkCapture()

    page.on(
        "request",
        capture.request,
    )

    page.on(
        "response",
        capture.response,
    )

    # --------------------------------------------------------
    # FINAL PUBLISH
    # --------------------------------------------------------

    if not click_final_publish(
        page
    ):

        print_network_errors(
            capture
        )

        print_visible_errors(
            page
        )

        save_debug(
            page,
            capture,
        )

        return None

    print()
    print(
        "============================================================"
    )
    print(
        "FINAL PUBLISH CLICKED"
    )
    print(
        "Waiting for Serey publication response..."
    )
    print(
        "============================================================"
    )

    # Give Serey enough time
    page.wait_for_timeout(
        15000
    )

    # --------------------------------------------------------
    # 1. NETWORK RESPONSE
    # --------------------------------------------------------

    network_urls = (
        find_url_in_network(
            capture
        )
    )

    for candidate in (
        network_urls
    ):

        print(
            f"✓ Network post URL candidate: "
            f"{candidate}"
        )

        verified = (
            verify_real_post_page(
                page,
                candidate,
                title,
            )
        )

        if verified:
            return verified

    # --------------------------------------------------------
    # 2. CURRENT PAGE URL
    # --------------------------------------------------------

    current_url = normalize_url(
        page.url
    )

    print(
        f"Current URL after publish: "
        f"{current_url}"
    )

    if is_real_post_url(
        current_url
    ):

        verified = (
            verify_real_post_page(
                page,
                current_url,
                title,
            )
        )

        if verified:
            return verified

    else:

        if current_url.lower().endswith(
            "/my-activity"
        ):

            print(
                "⚠ my-activity detected."
            )

            print(
                "⚠ This is NOT accepted "
                "as the published URL."
            )

    # --------------------------------------------------------
    # 3. CURRENT PAGE LINKS
    # --------------------------------------------------------

    candidate = (
        find_post_link_on_page(
            page,
            title,
        )
    )

    if candidate:

        verified = (
            verify_real_post_page(
                page,
                candidate,
                title,
            )
        )

        if verified:
            return verified

    # --------------------------------------------------------
    # 4. ACTIVITY PAGE
    # --------------------------------------------------------

    print()
    print(
        "No direct post URL found."
    )

    print(
        "Checking profile activity "
        "for the actual post link..."
    )

    verified = (
        search_activity_for_post(
            page,
            title,
        )
    )

    if verified:

        return verified

    # --------------------------------------------------------
    # FAILURE
    # --------------------------------------------------------

    print()
    print(
        "============================================================"
    )
    print(
        "❌ PUBLICATION COULD NOT BE VERIFIED"
    )
    print(
        "============================================================"
    )

    print(
        "my-activity was NOT accepted "
        "as a published post URL."
    )

    print(
        f"Current URL: {page.url}"
    )

    print_network_errors(
        capture
    )

    print_visible_errors(
        page
    )

    save_debug(
        page,
        capture,
    )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "\n"
        "============================================================\n"
        "STEEM -> SEREY AUTO SYNC\n"
        "============================================================\n"
        "• First image = thumbnail\n"
        "• Thumbnail crop = automatic\n"
        "• Crop modal = fully closed before Publish\n"
        "• Body images = removed\n"
        "• Steem HTML/Markdown = cleaned\n"
        "• Posts per run = 1\n"
        "• Sync period = 365 days\n"
        "• REAL published URL = REQUIRED\n"
        "• my-activity = NEVER accepted\n"
        "• Date handling = UTC SAFE\n"
        "============================================================"
    )

    synced = load_synced()

    print(
        f"Previously synced: "
        f"{len(synced)}"
    )

    print(
        f"Getting posts from "
        f"@{STEEM_USERNAME}..."
    )

    posts = get_posts()

    unsynced = [
        post
        for post in posts
        if (
            f"{post['author']}/"
            f"{post['permlink']}"
            not in synced
        )
    ]

    print(
        f"Unsynced posts: "
        f"{len(unsynced)}"
    )

    selected = (
        unsynced[
            :POSTS_PER_RUN
        ]
    )

    print(
        f"Posts selected this run: "
        f"{len(selected)}"
    )

    if not selected:

        print(
            "✓ Nothing to sync."
        )

        return

    for post in selected:

        print(
            f"Selected: "
            f"{post['author']}/"
            f"{post['permlink']}"
        )

        print(
            f"Created: "
            f"{post['created'].isoformat()}"
        )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            ),
        )

        page = context.new_page()

        # Accept browser dialogs
        page.on(
            "dialog",
            lambda dialog:
                dialog.accept(),
        )

        try:

            if not login(page):

                print(
                    "❌ Cannot continue "
                    "without Serey login."
                )

                return

            for post in selected:

                post_key = (
                    f"{post['author']}/"
                    f"{post['permlink']}"
                )

                print()
                print(
                    "============================================================"
                )

                print(
                    f"STARTING POST: "
                    f"{post_key}"
                )

                print(
                    "============================================================"
                )

                published_url = (
                    publish_post(
                        page,
                        post,
                    )
                )

                if published_url:

                    # FINAL SAFETY CHECK
                    if not is_real_post_url(
                        published_url
                    ):

                        print(
                            "❌ SAFETY CHECK FAILED."
                        )

                        print(
                            f"Rejected URL: "
                            f"{published_url}"
                        )

                        continue

                    print()
                    print(
                        "============================================================"
                    )

                    print(
                        "✓✓✓ PUBLISHED SUCCESSFULLY ✓✓✓"
                    )

                    print(
                        "============================================================"
                    )

                    print(
                        f"Published URL:\n"
                        f"{published_url}"
                    )

                    print(
                        "============================================================"
                    )

                    # ONLY after real URL verification
                    synced.add(
                        post_key
                    )

                    save_synced(
                        synced
                    )

                    print(
                        f"✓ SAVED AS SYNCED: "
                        f"{post_key}"
                    )

                    print(
                        f"✓ SEREY URL: "
                        f"{published_url}"
                    )

                else:

                    print()
                    print(
                        f"⚠ FAILED: "
                        f"{post_key}"
                    )

                    print(
                        "⚠ This post will NOT be "
                        "added to synced_posts.json."
                    )

                # ------------------------------------------------
                # Remove temporary thumbnail
                # ------------------------------------------------

                if os.path.exists(
                    TEMP_IMAGE
                ):

                    try:

                        os.remove(
                            TEMP_IMAGE
                        )

                        print(
                            "Removed temporary "
                            "thumbnail."
                        )

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

    print()
    print(
        "============================================================"
    )
    print(
        "RUN FINISHED"
    )
    print(
        "============================================================"
    )


if __name__ == "__main__":
    main()
