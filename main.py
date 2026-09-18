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

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()

# Current Bengali Serey
SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/write/new"

SYNC_FILE = "synced_posts.json"

TEMP_IMAGE = "temp_image.jpg"

POSTS_PER_RUN = 1

# Last 1 year
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
                timeout=20
            )

            r.raise_for_status()

            data = r.json()

            if "error" in data:
                raise Exception(
                    data["error"]
                )

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

    raise Exception(
        "All Steem RPC nodes failed"
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
            encoding="utf-8"
        ) as f:

            return set(
                json.load(f)
            )

    except Exception:

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
# EXTRACT IMAGE URLS
# ============================================================

def extract_images(body, metadata):

    images = []

    # --------------------------------------------------------
    # 1. Images from Steem metadata
    # --------------------------------------------------------

    try:

        meta = json.loads(
            metadata or "{}"
        )

        meta_images = meta.get(
            "image",
            []
        )

        if isinstance(
            meta_images,
            list
        ):

            for url in meta_images:

                if (
                    isinstance(url, str)
                    and url.startswith("http")
                    and url not in images
                ):
                    images.append(url)

    except Exception:
        pass

    # --------------------------------------------------------
    # 2. Markdown images inside BODY
    # --------------------------------------------------------

    markdown_images = re.findall(
        r'!\[[^\]]*\]\((https?://[^)\s]+)',
        body,
        flags=re.I
    )

    for url in markdown_images:

        url = url.strip()

        if url not in images:
            images.append(url)

    # --------------------------------------------------------
    # 3. HTML image tags
    # --------------------------------------------------------

    html_images = re.findall(
        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
        body,
        flags=re.I
    )

    for url in html_images:

        url = url.strip()

        if url not in images:
            images.append(url)

    return images


# ============================================================
# CLEAN BODY
#
# IMPORTANT:
# We DO NOT remove images from body.
# ============================================================

def clean_post(body, metadata):

    body = body or ""

    images = extract_images(
        body,
        metadata
    )

    # Only reduce excessive blank lines.
    # DO NOT remove image markdown.
    body = re.sub(
        r'\n{4,}',
        '\n\n\n',
        body
    )

    return body.strip(), images


# ============================================================
# GET STEEM POSTS - LAST 1 YEAR
# ============================================================

def get_posts():

    print(
        f"Getting posts from @{STEEM_USERNAME}...",
        flush=True
    )

    cutoff = datetime.now(
        timezone.utc
    ) - timedelta(
        days=DAYS_TO_SYNC
    )

    print(
        f"Sync period: last {DAYS_TO_SYNC} days",
        flush=True
    )

    print(
        f"Cutoff: {cutoff.isoformat()}",
        flush=True
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None

    while len(posts) < 5000:

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

        result = rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )

        if not result:
            break

        batch = (
            result[1:]
            if start_author
            else result
        )

        if not batch:
            break

        reached_cutoff = False

        for p in batch:

            if p.get(
                "author"
            ) != STEEM_USERNAME:
                continue

            author = p.get(
                "author",
                ""
            )

            permlink = p.get(
                "permlink",
                ""
            )

            if not permlink:
                continue

            # ------------------------------------------------
            # DATE
            # ------------------------------------------------

            created = p.get(
                "created",
                ""
            )

            try:

                created_dt = datetime.fromisoformat(
                    created.replace(
                        "Z",
                        "+00:00"
                    )
                )

            except Exception:

                # If date cannot be parsed,
                # keep the post rather than losing it.
                created_dt = None

            # ------------------------------------------------
            # Stop when posts become older than 1 year
            # ------------------------------------------------

            if (
                created_dt
                and created_dt < cutoff
            ):

                reached_cutoff = True

                continue

            # ------------------------------------------------
            # UNIQUE ID
            # ------------------------------------------------

            pid = (
                f"{author}/{permlink}"
            )

            if pid in seen:
                continue

            seen.add(pid)

            # ------------------------------------------------
            # BODY + IMAGES
            # ------------------------------------------------

            body, images = clean_post(
                p.get(
                    "body",
                    ""
                ),
                p.get(
                    "json_metadata",
                    "{}"
                )
            )

            posts.append({

                "id": pid,

                "title": p.get(
                    "title",
                    ""
                ).strip(),

                "body": body,

                "images": images,

                "category": p.get(
                    "category",
                    ""
                ),

                "created": created

            })

        # ----------------------------------------------------
        # If this batch has reached the 1-year cutoff,
        # we can stop after processing it.
        # ----------------------------------------------------

        if reached_cutoff:
            print(
                "✓ Reached 1-year cutoff.",
                flush=True
            )
            break

        # ----------------------------------------------------
        # Pagination
        # ----------------------------------------------------

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

        time.sleep(0.3)

    # ========================================================
    # OLDEST -> NEWEST
    # ========================================================

    def sort_key(post):

        try:

            return datetime.fromisoformat(
                post["created"].replace(
                    "Z",
                    "+00:00"
                )
            )

        except Exception:

            return datetime.min.replace(
                tzinfo=timezone.utc
            )

    posts.sort(
        key=sort_key
    )

    print(
        f"Total posts in last 1 year: {len(posts)}",
        flush=True
    )

    if posts:

        print(
            f"Oldest: {posts[0]['created']} "
            f"- {posts[0]['title']}",
            flush=True
        )

        print(
            f"Newest: {posts[-1]['created']} "
            f"- {posts[-1]['title']}",
            flush=True
        )

    return posts


# ============================================================
# DOWNLOAD ONE IMAGE
# ============================================================

def download_image(url, filename):

    if not url:
        return None

    try:

        print(
            f"Downloading image: {url}",
            flush=True
        )

        r = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        r.raise_for_status()

        content_type = (
            r.headers
            .get(
                "content-type",
                ""
            )
            .lower()
        )

        if "image" not in content_type:

            print(
                "⚠️ URL did not return an image.",
                flush=True
            )

            return None

        with open(
            filename,
            "wb"
        ) as f:

            f.write(
                r.content
            )

        return filename

    except Exception as e:

        print(
            f"Image download failed: {e}",
            flush=True
        )

        return None


# ============================================================
# DOWNLOAD ALL BODY IMAGES
# ============================================================

def download_all_images(image_urls):

    downloaded = []

    for index, url in enumerate(
        image_urls,
        start=1
    ):

        # Determine extension
        path = urlparse(url).path

        ext = os.path.splitext(
            path
        )[1].lower()

        if ext not in [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp"
        ]:

            ext = ".jpg"

        filename = (
            f"steem_image_{index}{ext}"
        )

        file_path = download_image(
            url,
            filename
        )

        if file_path:

            downloaded.append({
                "url": url,
                "path": file_path
            })

    print(
        f"✓ Downloaded images: "
        f"{len(downloaded)}/{len(image_urls)}",
        flush=True
    )

    return downloaded


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

    page.wait_for_timeout(
        5000
    )

    login_selectors = [
        'a:has-text("Log in")',
        'button:has-text("Log in")',
        'a:has-text("Log In")',
        'button:has-text("Log In")'
    ]

    clicked = False

    for selector in login_selectors:

        try:

            loc = page.locator(
                selector
            ).first

            if loc.is_visible(
                timeout=3000
            ):

                loc.click(
                    force=True
                )

                clicked = True
                break

        except Exception:
            pass

    if not clicked:

        raise Exception(
            "Serey login button not found."
        )

    page.wait_for_timeout(
        3000
    )

    username_selectors = [
        'input[placeholder*="Username"]',
        'input[placeholder*="username"]',
        'input[name="username"]',
        'input[type="text"]'
    ]

    username_box = None

    for selector in username_selectors:

        try:

            loc = page.locator(
                selector
            ).first

            if loc.is_visible(
                timeout=2000
            ):

                username_box = loc
                break

        except Exception:
            pass

    if not username_box:

        raise Exception(
            "Serey username input not found."
        )

    username_box.fill(
        SEREY_LOGIN
    )

    key_selectors = [
        'input[placeholder*="Private Key"]',
        'input[placeholder*="private key"]',
        'input[type="password"]'
    ]

    key_box = None

    for selector in key_selectors:

        try:

            loc = page.locator(
                selector
            ).first

            if loc.is_visible(
                timeout=2000
            ):

                key_box = loc
                break

        except Exception:
            pass

    if not key_box:

        raise Exception(
            "Serey private key input not found."
        )

    key_box.fill(
        SEREY_PASSWORD
    )

    submit_selectors = [
        'button:has-text("Log in")',
        'button:has-text("Log In")',
        'button[type="submit"]'
    ]

    submitted = False

    for selector in submit_selectors:

        try:

            loc = page.locator(
                selector
            ).last

            if loc.is_visible(
                timeout=3000
            ):

                loc.click(
                    force=True
                )

                submitted = True
                break

        except Exception:
            pass

    if not submitted:

        raise Exception(
            "Serey login submit button not found."
        )

    page.wait_for_timeout(
        8000
    )

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )


# ============================================================
# FIND TITLE
# ============================================================

def find_title_box(page):

    selectors = [
        'input[placeholder="Enter title..."]',
        'input[placeholder*="Enter title"]',
        'input[placeholder*="Title"]',
        'textarea[placeholder*="Enter title"]'
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            ).first

            if loc.is_visible(
                timeout=2500
            ):

                return loc

        except Exception:
            pass

    return None


# ============================================================
# FIND BODY EDITOR
# ============================================================

def find_editor(page):

    selectors = [
        'textarea[placeholder="Enter content..."]',
        'textarea[placeholder*="Enter content"]',
        'div[contenteditable="true"]',
        '[contenteditable="true"]'
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            ).first

            if loc.is_visible(
                timeout=2500
            ):

                return loc

        except Exception:
            pass

    return None


# ============================================================
# UPLOAD INLINE IMAGES IF POSSIBLE
# ============================================================

def try_upload_body_images(
    page,
    downloaded_images
):

    if not downloaded_images:
        return

    print(
        "Checking Serey editor for image upload...",
        flush=True
    )

    # Look for image-related file inputs
    file_inputs = page.locator(
        'input[type="file"]'
    )

    count = file_inputs.count()

    print(
        f"File inputs detected: {count}",
        flush=True
    )

    if count <= 1:

        print(
            "⚠️ No separate inline-image upload input detected.",
            flush=True
        )

        print(
            "✓ Original image URLs remain in the body.",
            flush=True
        )

        return

    # If multiple file inputs exist, the first one is
    # normally thumbnail and later ones may belong to editor.

    for index, item in enumerate(
        downloaded_images,
        start=1
    ):

        try:

            target_index = index

            if target_index >= count:
                break

            file_inputs.nth(
                target_index
            ).set_input_files(
                item["path"]
            )

            print(
                f"✓ Inline image upload attempted: "
                f"{item['path']}",
                flush=True
            )

            page.wait_for_timeout(
                3000
            )

        except Exception as e:

            print(
                f"⚠️ Inline image upload failed: {e}",
                flush=True
            )


# ============================================================
# VERIFY
# ============================================================

def verify(page, title):

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    for _ in range(10):

        page.wait_for_timeout(
            3000
        )

        url = page.url

        print(
            f"Current URL: {url}",
            flush=True
        )

        if "/write/new" not in url:

            print(
                "✓ SUCCESS: Serey left the Write page.",
                flush=True
            )

            return True

        success_texts = [
            "Successfully posted",
            "Successfully published",
            "Article published",
            "Post published",
            "successfully posted your article"
        ]

        for text in success_texts:

            try:

                if page.get_by_text(
                    text,
                    exact=False
                ).is_visible(
                    timeout=1000
                ):

                    print(
                        f"✓ SUCCESS MESSAGE DETECTED: {text}",
                        flush=True
                    )

                    return True

            except Exception:
                pass

    print(
        "❌ Publication could not be verified.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH
# ============================================================

def publish(page, post):

    print("-" * 60)

    print(
        f"Publishing: {post['title']}",
        flush=True
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
        f"Write page: {page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_box = find_title_box(
        page
    )

    if not title_box:

        raise Exception(
            "Serey title input not found."
        )

    title_box.click()

    title_box.fill(
        post["title"]
    )

    print(
        "✓ Title filled",
        flush=True
    )

    page.wait_for_timeout(
        1000
    )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    editor = find_editor(
        page
    )

    if not editor:

        raise Exception(
            "Serey content editor not found."
        )

    editor.click()

    try:

        editor.fill(
            post["body"]
        )

    except Exception:

        page.keyboard.insert_text(
            post["body"]
        )

    print(
        "✓ Body filled",
        flush=True
    )

    # --------------------------------------------------------
    # IMAGE INFORMATION
    # --------------------------------------------------------

    image_urls = post.get(
        "images",
        []
    )

    print(
        f"Images found in post: "
        f"{len(image_urls)}",
        flush=True
    )

    # --------------------------------------------------------
    # DOWNLOAD BODY IMAGES
    # --------------------------------------------------------

    downloaded_images = (
        download_all_images(
            image_urls
        )
        if image_urls
        else []
    )

    # --------------------------------------------------------
    # THUMBNAIL
    #
    # Use first reachable image as thumbnail.
    # --------------------------------------------------------

    if downloaded_images:

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            count = file_inputs.count()

            if count > 0:

                file_inputs.first.set_input_files(
                    downloaded_images[0]["path"]
                )

                print(
                    "✓ Thumbnail uploaded",
                    flush=True
                )

                page.wait_for_timeout(
                    5000
                )

        except Exception as e:

            print(
                f"⚠️ Thumbnail upload failed: {e}",
                flush=True
            )

    # --------------------------------------------------------
    # INLINE IMAGE ATTEMPT
    # --------------------------------------------------------

    try_upload_body_images(
        page,
        downloaded_images
    )

    # --------------------------------------------------------
    # PUBLISH BUTTON
    # --------------------------------------------------------

    print(
        "Looking for Publish button...",
        flush=True
    )

    publish_selectors = [
        'button:has-text("Publish")',
        'button:has-text("publish")',
        '[role="button"]:has-text("Publish")',
        'button[type="submit"]'
    ]

    clicked = False

    for selector in publish_selectors:

        try:

            buttons = page.locator(
                selector
            )

            count = buttons.count()

            for i in range(count):

                btn = buttons.nth(i)

                if btn.is_visible(
                    timeout=1000
                ):

                    btn.scroll_into_view_if_needed()

                    btn.click(
                        force=True
                    )

                    print(
                        f"✓ Publish button clicked: {selector}",
                        flush=True
                    )

                    clicked = True
                    break

            if clicked:
                break

        except Exception:
            pass

    if not clicked:

        print(
            "Trying JavaScript Publish click...",
            flush=True
        )

        result = page.evaluate("""
        () => {
            const elements = Array.from(
                document.querySelectorAll(
                    'button, [role="button"]'
                )
            );

            const target = elements.find(el => {
                const text =
                    (el.innerText || el.textContent || '')
                    .trim()
                    .toLowerCase();

                return text === 'publish';
            });

            if (target) {
                target.click();
                return true;
            }

            return false;
        }
        """)

        if result:

            print(
                "✓ JavaScript Publish click executed",
                flush=True
            )

            clicked = True

    if not clicked:

        raise Exception(
            "Serey Publish button not found."
        )

    # --------------------------------------------------------
    # FINAL CONFIRMATION
    # --------------------------------------------------------

    page.wait_for_timeout(
        5000
    )

    print(
        "Checking for final confirmation...",
        flush=True
    )

    modal_selectors = [
        'div[role="dialog"] button:has-text("Publish")',
        'div[role="dialog"] button:has-text("Confirm")',
        'div[role="dialog"] button:has-text("Submit")',
        '[class*="modal"] button:has-text("Publish")',
        '[class*="modal"] button:has-text("Confirm")',
        '[class*="dialog"] button:has-text("Publish")',
        '[class*="dialog"] button:has-text("Confirm")'
    ]

    final_clicked = False

    for selector in modal_selectors:

        try:

            loc = page.locator(
                selector
            ).last

            if loc.is_visible(
                timeout=1500
            ):

                loc.click(
                    force=True
                )

                print(
                    f"✓ Final confirmation clicked: {selector}",
                    flush=True
                )

                final_clicked = True
                break

        except Exception:
            pass

    if not final_clicked:

        print(
            "No confirmation modal detected.",
            flush=True
        )

    page.wait_for_timeout(
        10000
    )

    return verify(
        page,
        post["title"]
    )


# ============================================================
# CLEAN TEMPORARY IMAGES
# ============================================================

def cleanup_images():

    patterns = [
        "steem_image_"
    ]

    for filename in os.listdir("."):

        if any(
            filename.startswith(prefix)
            for prefix in patterns
        ):

            try:

                os.remove(
                    filename
                )

            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("STEEM -> SEREY AUTO SYNC")
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

    # --------------------------------------------------------
    # OLDest -> NEWest
    # POSTS_PER_RUN = 1
    # --------------------------------------------------------

    posts_to_run = new_posts[
        :POSTS_PER_RUN
    ]

    if not posts_to_run:

        print(
            "Nothing to publish.",
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
                "Chrome/122.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        try:

            login(page)

            for post in posts_to_run:

                try:

                    if publish(
                        page,
                        post
                    ):

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

                    else:

                        print(
                            "⚠️ NOT SAVED AS SYNCED.",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publish error: {e}",
                        flush=True
                    )

        finally:

            cleanup_images()

            if os.path.exists(
                TEMP_IMAGE
            ):

                try:
                    os.remove(
                        TEMP_IMAGE
                    )
                except Exception:
                    pass

            browser.close()

    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()

