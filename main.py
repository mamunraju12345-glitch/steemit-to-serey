import os
import json
import re
import time
import requests

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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


# ============================================================
# RPC
# ============================================================

def rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    for node in STEEM_NODES:

        try:

            print(f"RPC: {node}")

            response = requests.post(
                node,
                json=payload,
                timeout=30,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Steem-Serey-Auto-Sync/1.0"
                }
            )

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                print(
                    f"RPC error from {node}: "
                    f"{data['error']}"
                )

                continue

            print(
                f"✓ RPC success: {node}"
            )

            return data.get("result")

        except Exception as e:

            print(
                f"RPC failed: {node}"
            )

            print(
                f"Reason: {e}"
            )

    raise RuntimeError(
        "All Steem RPC nodes failed."
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
            f"Could not read {SYNC_FILE}: {e}"
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
# IMAGE EXTRACTION
# ============================================================

def extract_images(post):

    images = []

    # --------------------------------------------------------
    # Steem metadata
    # --------------------------------------------------------

    try:

        metadata_raw = post.get(
            "json_metadata",
            "{}"
        )

        if isinstance(metadata_raw, str):

            metadata = json.loads(
                metadata_raw
            )

        else:

            metadata = metadata_raw

        if isinstance(metadata, dict):

            metadata_images = metadata.get(
                "image",
                []
            )

            if isinstance(
                metadata_images,
                str
            ):

                metadata_images = [
                    metadata_images
                ]

            if isinstance(
                metadata_images,
                list
            ):

                for url in metadata_images:

                    if isinstance(
                        url,
                        str
                    ):

                        images.append(
                            url
                        )

    except Exception:
        pass

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    body = post.get(
        "body",
        ""
    ) or ""

    # Markdown images
    markdown_images = re.findall(
        r'!\[[^\]]*\]\((https?://[^)\s]+)',
        body,
        flags=re.IGNORECASE
    )

    images.extend(
        markdown_images
    )

    # HTML images
    html_images = re.findall(
        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
        body,
        flags=re.IGNORECASE
    )

    images.extend(
        html_images
    )

    # --------------------------------------------------------
    # Unique URLs
    # --------------------------------------------------------

    result = []

    for url in images:

        if not isinstance(
            url,
            str
        ):
            continue

        url = url.strip()

        if not url.startswith(
            ("http://", "https://")
        ):
            continue

        if url not in result:

            result.append(
                url
            )

    return result


# ============================================================
# CLEAN BODY
# ============================================================

def clean_post(body):

    if not body:
        return ""

    body = body.replace(
        "\r\n",
        "\n"
    )

    body = body.replace(
        "\r",
        "\n"
    )

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

    print(
        f"Getting posts from @{STEEM_USERNAME}..."
    )

    print(
        f"Sync period: last {DAYS_TO_SYNC} days"
    )

    now = datetime.now(
        timezone.utc
    )

    cutoff = (
        now -
        timedelta(
            days=DAYS_TO_SYNC
        )
    )

    print(
        f"Cutoff: {cutoff.isoformat()}"
    )

    posts = []

    start_author = STEEM_USERNAME
    start_permlink = None

    page_number = 0

    while True:

        page_number += 1

        params = [{
            "tag": STEEM_USERNAME,
            "limit": 100,
            "start_author": start_author,
            "start_permlink": start_permlink
        }]

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        print(
            f"Steem page {page_number}: "
            f"{len(result)} results"
        )

        reached_cutoff = False

        for post in result:

            created = post.get(
                "created",
                ""
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

                    created_dt = (
                        created_dt.replace(
                            tzinfo=timezone.utc
                        )
                    )

                created_dt = (
                    created_dt.astimezone(
                        timezone.utc
                    )
                )

            except Exception as e:

                print(
                    f"Skipping invalid date "
                    f"{created}: {e}"
                )

                continue

            if created_dt < cutoff:

                reached_cutoff = True

                continue

            if post.get(
                "author"
            ) != STEEM_USERNAME:

                continue

            post_id = (
                f"{post.get('author')}/"
                f"{post.get('permlink')}"
            )

            post["_created_dt"] = (
                created_dt
            )

            post["_post_id"] = (
                post_id
            )

            posts.append(
                post
            )

        if reached_cutoff:
            break

        last_post = result[-1]

        last_author = (
            last_post.get(
                "author"
            )
        )

        last_permlink = (
            last_post.get(
                "permlink"
            )
        )

        if not last_author:
            break

        if not last_permlink:
            break

        start_author = last_author
        start_permlink = last_permlink

        if len(result) < 100:
            break

    # --------------------------------------------------------
    # Oldest -> newest
    # --------------------------------------------------------

    posts.sort(
        key=lambda p: p["_created_dt"]
    )

    print()

    print(
        f"Total posts in last "
        f"{DAYS_TO_SYNC} days: "
        f"{len(posts)}"
    )

    if posts:

        print(
            "Oldest:",
            posts[0][
                "_created_dt"
            ].isoformat(),
            posts[0][
                "_post_id"
            ]
        )

        print(
            "Newest:",
            posts[-1][
                "_created_dt"
            ].isoformat(),
            posts[-1][
                "_post_id"
            ]
        )

    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(
    url,
    filename
):

    try:

        print()
        print(
            "Downloading image:"
        )

        print(url)

        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/130 Safari/537.36"
                )
            },
            timeout=30,
            stream=True
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

        parsed = urlparse(
            url
        )

        path = parsed.path.lower()

        allowed_extension = (
            path.endswith(".jpg")
            or path.endswith(".jpeg")
            or path.endswith(".png")
            or path.endswith(".gif")
            or path.endswith(".webp")
            or path.endswith(".bmp")
            or path.endswith(".svg")
        )

        if (
            "image/" not in content_type
            and not allowed_extension
        ):

            print(
                "Skipped non-image:"
                f" {content_type}"
            )

            return None

        with open(
            filename,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):

                if chunk:
                    f.write(chunk)

        if not os.path.exists(
            filename
        ):

            return None

        size = os.path.getsize(
            filename
        )

        if size <= 0:

            os.remove(
                filename
            )

            return None

        print(
            f"✓ Image downloaded: "
            f"{filename} "
            f"({size} bytes)"
        )

        return filename

    except Exception as e:

        print(
            f"✗ Image download failed:"
        )

        print(url)

        print(
            f"Reason: {e}"
        )

        try:

            if os.path.exists(
                filename
            ):

                os.remove(
                    filename
                )

        except Exception:
            pass

        return None


# ============================================================
# DOWNLOAD ALL IMAGES
# ============================================================

def download_all_images(
    image_urls
):

    downloaded = []

    if not image_urls:

        print(
            "No images found in post."
        )

        return downloaded

    print()
    print(
        f"Images found in post: "
        f"{len(image_urls)}"
    )

    for index, url in enumerate(
        image_urls,
        start=1
    ):

        parsed = urlparse(
            url
        )

        extension = os.path.splitext(
            parsed.path
        )[1].lower()

        if extension not in [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".bmp",
            ".svg"
        ]:

            extension = ".jpg"

        filename = (
            f"{IMAGE_PREFIX}"
            f"{index}"
            f"{extension}"
        )

        result = download_image(
            url,
            filename
        )

        if result:

            downloaded.append(
                result
            )

    print()

    print(
        f"Downloaded images: "
        f"{len(downloaded)}/"
        f"{len(image_urls)}"
    )

    return downloaded


# ============================================================
# SEREY LOGIN
# ============================================================

def login(page):

    print()
    print(
        "Logging into Serey..."
    )

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        3000
    )

    username_selectors = [
        'input[name="username"]',
        'input[name="login"]',
        'input[placeholder*="username" i]',
        'input[placeholder*="email" i]',
        'input[type="text"]'
    ]

    password_selectors = [
        'input[type="password"]',
        'input[name="password"]'
    ]

    username_box = None
    password_box = None

    for selector in username_selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    username_box = (
                        candidate
                    )

                    break

            if username_box:
                break

        except Exception:
            pass

    for selector in password_selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    password_box = (
                        candidate
                    )

                    break

            if password_box:
                break

        except Exception:
            pass

    if not username_box or not password_box:

        for selector in [
            'text=Login',
            'text=Log in',
            'text=Sign in'
        ]:

            try:

                locator = page.locator(
                    selector
                )

                for i in range(
                    locator.count()
                ):

                    candidate = locator.nth(
                        i
                    )

                    if candidate.is_visible():

                        candidate.click()

                        page.wait_for_timeout(
                            2000
                        )

                        break

            except Exception:
                pass

            if username_box and password_box:
                break

        # Find again
        for selector in username_selectors:

            try:

                locator = page.locator(
                    selector
                )

                for i in range(
                    locator.count()
                ):

                    candidate = locator.nth(
                        i
                    )

                    if candidate.is_visible():

                        username_box = (
                            candidate
                        )

                        break

                if username_box:
                    break

            except Exception:
                pass

        for selector in password_selectors:

            try:

                locator = page.locator(
                    selector
                )

                for i in range(
                    locator.count()
                ):

                    candidate = locator.nth(
                        i
                    )

                    if candidate.is_visible():

                        password_box = (
                            candidate
                        )

                        break

                if password_box:
                    break

            except Exception:
                pass

    if not username_box:

        raise RuntimeError(
            "Serey username input not found."
        )

    if not password_box:

        raise RuntimeError(
            "Serey password input not found."
        )

    username_box.fill(
        SEREY_LOGIN
    )

    password_box.fill(
        SEREY_PASSWORD
    )

    submitted = False

    for selector in [
        'button[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
        'input[type="submit"]'
    ]:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    candidate.click()

                    submitted = True

                    page.wait_for_timeout(
                        5000
                    )

                    break

            if submitted:
                break

        except Exception:
            pass

    if not submitted:

        password_box.press(
            "Enter"
        )

        page.wait_for_timeout(
            5000
        )

    print(
        f"After login URL: "
        f"{page.url}"
    )

    if "login" in page.url.lower():

        raise RuntimeError(
            "Serey login failed."
        )

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!"
    )


# ============================================================
# FIND TITLE
# ============================================================

def find_title_box(page):

    print(
        "Looking for Serey title field..."
    )

    page.wait_for_timeout(
        3000
    )

    selectors = [
        'input[placeholder="Enter title..."]',
        'input[placeholder*="Enter title" i]',
        'input[name="title"]',
        'input[aria-label*="title" i]',
        'textarea[placeholder="Enter title..."]',
        'textarea[placeholder*="title" i]'
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            print(
                f"Checking: "
                f"{selector} -> {count}"
            )

            for i in range(count):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    print(
                        f"✓ Title field found: "
                        f"{selector}"
                    )

                    return candidate

        except Exception as e:

            print(
                f"Selector error: "
                f"{e}"
            )

    # Diagnostic information
    try:

        fields = page.locator(
            "input, textarea"
        )

        print(
            f"Visible form fields: "
            f"{fields.count()}"
        )

        for i in range(
            fields.count()
        ):

            field = fields.nth(
                i
            )

            try:

                if not field.is_visible():
                    continue

                print(
                    f"Field {i}: "
                    f"type={field.get_attribute('type')} "
                    f"name={field.get_attribute('name')} "
                    f"placeholder={field.get_attribute('placeholder')} "
                    f"aria={field.get_attribute('aria-label')}"
                )

            except Exception:
                pass

    except Exception as e:

        print(
            f"Field inspection failed: {e}"
        )

    return None


# ============================================================
# FIND EDITOR
# ============================================================

def find_editor(page):

    page.wait_for_timeout(
        2000
    )

    selectors = [
        'textarea[placeholder="Enter content..."]',
        'textarea[placeholder*="Enter content" i]',
        'textarea[name="content"]',
        'textarea[placeholder*="content" i]',
        '.ProseMirror',
        '[contenteditable="true"]'
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    print(
                        f"✓ Editor found: "
                        f"{selector}"
                    )

                    return candidate

        except Exception:
            pass

    return None


# ============================================================
# FILE INPUT INFORMATION
# ============================================================

def inspect_file_inputs(page):

    try:

        inputs = page.locator(
            'input[type="file"]'
        )

        count = inputs.count()

        print(
            f"File inputs detected: "
            f"{count}"
        )

        for i in range(count):

            try:

                element = inputs.nth(
                    i
                )

                print(
                    f"File input {i}: "
                    f"accept="
                    f"{element.get_attribute('accept')} "
                    f"name="
                    f"{element.get_attribute('name')} "
                    f"multiple="
                    f"{element.get_attribute('multiple')}"
                )

            except Exception:
                pass

        return inputs

    except Exception as e:

        print(
            f"File input inspection failed: {e}"
        )

        return None


# ============================================================
# UPLOAD THUMBNAIL
# ============================================================

def upload_thumbnail(
    page,
    image_file
):

    if not image_file:
        return False

    print()
    print(
        "Uploading thumbnail..."
    )

    inputs = inspect_file_inputs(
        page
    )

    if not inputs:
        return False

    count = inputs.count()

    if count <= 0:

        print(
            "No file input available "
            "for thumbnail."
        )

        return False

    try:

        inputs.nth(0).set_input_files(
            image_file
        )

        print(
            f"✓ Thumbnail file selected: "
            f"{image_file}"
        )

        page.wait_for_timeout(
            2000
        )

        return True

    except Exception as e:

        print(
            f"✗ Thumbnail upload failed: "
            f"{e}"
        )

        return False


# ============================================================
# BODY IMAGE UPLOAD
# ============================================================

def upload_body_images(
    page,
    downloaded_images
):

    if not downloaded_images:

        return False

    print()
    print(
        "Looking for Serey body image upload..."
    )

    inputs = inspect_file_inputs(
        page
    )

    if not inputs:

        raise RuntimeError(
            "Serey body image upload input "
            "was not found."
        )

    count = inputs.count()

    print(
        f"Total file inputs: {count}"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # We cannot assume that input #1 is an inline
    # image uploader. If there is only one input,
    # it is most likely the thumbnail uploader.
    # --------------------------------------------------------

    if count <= 1:

        raise RuntimeError(
            "Serey currently exposes only one "
            "file input on the write page. "
            "Inline body image upload could not "
            "be verified."
        )

    uploaded_count = 0

    for index, image_file in enumerate(
        downloaded_images,
        start=1
    ):

        if index >= count:
            break

        try:

            print(
                f"Uploading body image "
                f"{index}: "
                f"{image_file}"
            )

            inputs.nth(
                index
            ).set_input_files(
                image_file
            )

            page.wait_for_timeout(
                1500
            )

            uploaded_count += 1

            print(
                f"✓ Body image file selected: "
                f"{image_file}"
            )

        except Exception as e:

            print(
                f"✗ Body image upload failed: "
                f"{image_file}"
            )

            print(
                f"Reason: {e}"
            )

    if uploaded_count == 0:

        raise RuntimeError(
            "No body images were uploaded."
        )

    print(
        f"Body images uploaded/selected: "
        f"{uploaded_count}/"
        f"{len(downloaded_images)}"
    )

    return True


# ============================================================
# VERIFY
# ============================================================

def verify(page):

    page.wait_for_timeout(
        5000
    )

    current_url = page.url

    print(
        f"After publish URL: "
        f"{current_url}"
    )

    if (
        current_url.rstrip("/")
        != NEW_POST.rstrip("/")
    ):

        return True

    return False


# ============================================================
# PUBLISH
# ============================================================

def publish(
    page,
    post
):

    title = (
        post.get(
            "title",
            ""
        )
        .strip()
    )

    body = clean_post(
        post.get(
            "body",
            ""
        )
    )

    print()
    print(
        "============================================================"
    )

    print(
        "Publishing post"
    )

    print(
        "============================================================"
    )

    print(
        f"Title: {title}"
    )

    print(
        f"Body length: "
        f"{len(body)} characters"
    )

    # --------------------------------------------------------
    # Open Serey write page
    # --------------------------------------------------------

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        5000
    )

    print(
        f"Write page: "
        f"{page.url}"
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
    # Images FIRST
    # --------------------------------------------------------

    image_urls = extract_images(
        post
    )

    print()
    print(
        f"Images found in post: "
        f"{len(image_urls)}"
    )

    downloaded_images = (
        download_all_images(
            image_urls
        )
    )

    # --------------------------------------------------------
    # If original post has images,
    # every image must be downloadable.
    # --------------------------------------------------------

    if image_urls:

        if len(downloaded_images) != len(
            image_urls
        ):

            raise RuntimeError(
                "Not all Steem images could "
                "be downloaded. Post was NOT "
                "published."
            )

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    try:

        tag_name = editor.evaluate(
            "(el) => el.tagName"
        )

        if tag_name.lower() == "textarea":

            editor.fill(
                body
            )

        else:

            editor.click()

            page.keyboard.insert_text(
                body
            )

        print(
            "✓ Body filled"
        )

    except Exception as e:

        raise RuntimeError(
            f"Could not fill Serey body: {e}"
        )

    # --------------------------------------------------------
    # Thumbnail
    # --------------------------------------------------------

    if downloaded_images:

        thumbnail_ok = upload_thumbnail(
            page,
            downloaded_images[0]
        )

        if not thumbnail_ok:

            raise RuntimeError(
                "Thumbnail upload failed."
            )

    # --------------------------------------------------------
    # BODY IMAGE UPLOAD
    # --------------------------------------------------------

    if downloaded_images:

        upload_body_images(
            page,
            downloaded_images
        )

    # --------------------------------------------------------
    # Publish button
    # --------------------------------------------------------

    publish_button = None

    selectors = [
        'button:has-text("Publish")',
        'button:has-text("PUBLISH")',
        'button:has-text("Publish Post")',
        'button[type="submit"]'
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    publish_button = (
                        candidate
                    )

                    break

            if publish_button:
                break

        except Exception:
            pass

    if not publish_button:

        raise RuntimeError(
            "Serey Publish button not found."
        )

    print(
        "✓ Publish button found"
    )

    publish_button.click()

    print(
        "✓ Publish button clicked"
    )

    page.wait_for_timeout(
        3000
    )

    # --------------------------------------------------------
    # Confirmation
    # --------------------------------------------------------

    confirmed = False

    for selector in [
        'button:has-text("Confirm")',
        'button:has-text("CONFIRM")',
        'button:has-text("Yes")'
    ]:

        try:

            locator = page.locator(
                selector
            )

            for i in range(
                locator.count()
            ):

                candidate = locator.nth(
                    i
                )

                if candidate.is_visible():

                    candidate.click(
                        timeout=3000
                    )

                    confirmed = True

                    print(
                        "✓ Publish confirmation clicked"
                    )

                    page.wait_for_timeout(
                        5000
                    )

                    break

            if confirmed:
                break

        except Exception:
            pass

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    if not verify(page):

        raise RuntimeError(
            "Serey publication could not "
            "be verified."
        )

    print()
    print(
        "✓ SEREY POST PUBLISHED SUCCESSFULLY!"
    )

    print(
        f"Final URL: {page.url}"
    )

    return page.url


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "============================================================"
    )

    print(
        "STEEM -> SEREY AUTO SYNC"
    )

    print(
        "============================================================"
    )

    print()

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

    # --------------------------------------------------------
    # Unsynced
    # --------------------------------------------------------

    unsynced_posts = [
        post
        for post in posts
        if post["_post_id"]
        not in synced
    ]

    print()

    print(
        f"Unsynced posts: "
        f"{len(unsynced_posts)}"
    )

    if not unsynced_posts:

        print(
            "✓ All posts are already synced."
        )

        return

    # --------------------------------------------------------
    # ONE POST
    # --------------------------------------------------------

    selected_posts = (
        unsynced_posts[
            :POSTS_PER_RUN
        ]
    )

    print()

    print(
        f"Posts selected this run: "
        f"{len(selected_posts)}"
    )

    for post in selected_posts:

        print()

        print(
            "------------------------------------------------------------"
        )

        print(
            f"Selected: "
            f"{post['_post_id']}"
        )

        print(
            f"Created: "
            f"{post['_created_dt'].isoformat()}"
        )

        print(
            f"Title: "
            f"{post.get('title', '')}"
        )

        print(
            "------------------------------------------------------------"
        )

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

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

            login(
                page
            )

            for post in selected_posts:

                post_id = post[
                    "_post_id"
                ]

                try:

                    print()
                    print(
                        "Starting sync:"
                    )

                    print(
                        post_id
                    )

                    serey_url = publish(
                        page,
                        post
                    )

                    # Only save after
                    # successful publication.
                    synced.add(
                        post_id
                    )

                    save_synced(
                        synced
                    )

                    print()

                    print(
                        f"✓ SAVED AS SYNCED: "
                        f"{serey_url}"
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

        finally:

            context.close()
            browser.close()

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    print()
    print(
        "Cleaning temporary images..."
    )

    for filename in os.listdir(
        "."
    ):

        if filename.startswith(
            IMAGE_PREFIX
        ):

            try:

                os.remove(
                    filename
                )

                print(
                    f"Removed: "
                    f"{filename}"
                )

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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
