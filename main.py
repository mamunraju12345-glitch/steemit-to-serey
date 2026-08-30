import os
import json
import re
import time
import requests
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
    "SEREY_PASSWORD", ""
).strip()

SEREY_BASE = "https://bengali.serey.io"
NEW_POST_URL = f"{SEREY_BASE}/blog/post/new"

DATA_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_thumbnail.jpg"

POSTS_PER_RUN = 1
MAX_POSTS = 5000

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

DEAD_IMAGE_DOMAINS = [
    "img.esteem.ws",
    "esteem.ws",
]


# ============================================================
# HELPERS
# ============================================================

def log(msg):
    print(msg, flush=True)


def post_id(post):
    return f'{post["author"]}/{post["permlink"]}'


def normalize(text):
    text = str(text or "").lower()
    text = re.sub(
        r"[^a-z0-9\u0980-\u09ff\s]",
        " ",
        text
    )
    return re.sub(r"\s+", " ", text).strip()


def is_dead_image(url):
    if not url:
        return True

    return any(
        domain in url.lower()
        for domain in DEAD_IMAGE_DOMAINS
    )


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

            log(f"Trying Steem RPC: {node}")

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

            log(
                f"RPC failed: {node} -> {e}"
            )

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed: {last_error}"
    )


# ============================================================
# SYNC DATABASE
# ============================================================

def load_synced():

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

        log(
            f"Could not read {DATA_FILE}: {e}"
        )

    return set()


def save_synced(posts):

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
    body,
    metadata
):

    image = None

    # Metadata image
    try:

        meta = json.loads(
            metadata or "{}"
        )

        images = meta.get(
            "image",
            []
        )

        if isinstance(images, list):

            for img in images:

                if (
                    isinstance(img, str)
                    and
                    not is_dead_image(img)
                ):

                    image = img
                    break

    except Exception:
        pass

    # Markdown image
    if not image:

        matches = re.findall(
            r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
            body or "",
            re.I
        )

        for img in matches:

            if not is_dead_image(img):
                image = img
                break

    # Direct image URL
    if not image:

        matches = re.findall(
            r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
            body or "",
            re.I
        )

        for img in matches:

            if not is_dead_image(img):
                image = img
                break

    # Remove markdown images
    clean = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body or ""
    )

    # Remove direct image URLs
    clean = re.sub(
        r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
        '',
        clean,
        flags=re.I
    )

    clean = re.sub(
        r'\n\s*\n\s*\n+',
        '\n\n',
        clean
    )

    return image, clean.strip()


# ============================================================
# FETCH STEEM POSTS
# ============================================================

def fetch_posts():

    log(
        f"\nFetching Steemit posts from @{STEEM_USERNAME}..."
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None

    batch_no = 0

    while len(posts) < MAX_POSTS:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author and start_permlink:

            params.update({
                "start_author": start_author,
                "start_permlink": start_permlink
            })

        batch_no += 1

        try:

            result = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                params
            )

        except Exception as e:

            log(f"Fetching failed: {e}")
            break

        if not result:
            break

        batch = (
            result[1:]
            if start_author and start_permlink
            else result
        )

        if not batch:
            break

        added = 0

        for item in batch:

            if item.get("author") != STEEM_USERNAME:
                continue

            author = item.get(
                "author",
                ""
            )

            permlink = item.get(
                "permlink",
                ""
            )

            if not permlink:
                continue

            pid = f"{author}/{permlink}"

            if pid in seen:
                continue

            seen.add(pid)

            image, body = (
                extract_image_and_clean_body(
                    item.get("body", ""),
                    item.get(
                        "json_metadata",
                        "{}"
                    )
                )
            )

            posts.append({
                "author": author,
                "permlink": permlink,
                "title": item.get(
                    "title",
                    ""
                ),
                "body": body,
                "image": image,

                # IMPORTANT:
                # Keep Steemit category
                "category": item.get(
                    "category",
                    ""
                ),

                "created": item.get(
                    "created",
                    ""
                )
            })

            added += 1

            if len(posts) >= MAX_POSTS:
                break

        log(
            f"Batch #{batch_no}: "
            f"{len(result)} received | "
            f"Total: {len(posts)}"
        )

        last = result[-1]

        new_author = last.get(
            "author"
        )

        new_permlink = last.get(
            "permlink"
        )

        if (
            new_author == start_author
            and
            new_permlink == start_permlink
        ):
            break

        if added == 0:
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

        time.sleep(.3)

    posts.reverse()

    log(
        f"\nTotal historical posts fetched: "
        f"{len(posts)}"
    )

    return posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(url):

    if is_dead_image(url):
        return None

    try:

        log(f"Downloading image: {url}")

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent":
                "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "content-type",
            ""
        ).lower()

        if "image" not in content_type:
            return None

        with open(
            TEMP_IMAGE,
            "wb"
        ) as f:

            f.write(
                response.content
            )

        log(
            "Thumbnail downloaded successfully!"
        )

        return TEMP_IMAGE

    except Exception as e:

        log(
            f"Image download failed: {e}"
        )

        return None


# ============================================================
# VISIBLE TEXT UTILITIES
# ============================================================

def visible_texts(page):

    texts = []

    selectors = [
        "button",
        "[role='button']",
        "[role='option']",
        ".ant-select-item-option",
        "li",
        "span",
        "div"
    ]

    for selector in selectors:

        try:

            loc = page.locator(selector)

            count = min(
                loc.count(),
                200
            )

            for i in range(count):

                try:

                    item = loc.nth(i)

                    if not item.is_visible(
                        timeout=200
                    ):
                        continue

                    text = item.inner_text(
                        timeout=300
                    ).strip()

                    if text:
                        texts.append(
                            text
                        )

                except Exception:
                    pass

        except Exception:
            pass

    return texts


# ============================================================
# CLICK EXACT TEXT
# ============================================================

def click_exact_text(
    page,
    text
):

    wanted = normalize(text)

    selectors = [
        "[role='option']",
        ".ant-select-item-option",
        "button",
        "[role='button']",
        "li",
        "span",
        "div"
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            count = min(
                loc.count(),
                200
            )

            for i in range(count):

                try:

                    item = loc.nth(i)

                    if not item.is_visible(
                        timeout=200
                    ):
                        continue

                    current = normalize(
                        item.inner_text(
                            timeout=300
                        )
                    )

                    if current == wanted:

                        item.click(
                            force=True,
                            timeout=5000
                        )

                        return True

                except Exception:
                    pass

        except Exception:
            pass

    return False


# ============================================================
# CATEGORY SELECTION
# ============================================================

def select_category(
    page,
    steem_category
):

    if not steem_category:

        log(
            "No Steemit category found. "
            "Skipping category."
        )

        return True

    log(
        f"Steemit category: "
        f"{steem_category}"
    )

    # Look for category control
    selectors = [
        'text="Select category"',
        '[placeholder*="Select category" i]',
        '[aria-label*="category" i]',
        '[role="combobox"]',
        '.ant-select-selector'
    ]

    clicked = False

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            count = min(
                loc.count(),
                20
            )

            for i in range(count):

                try:

                    item = loc.nth(i)

                    if item.is_visible(
                        timeout=300
                    ):

                        item.click(
                            force=True,
                            timeout=5000
                        )

                        clicked = True
                        break

                except Exception:
                    pass

            if clicked:
                break

        except Exception:
            pass

    if not clicked:

        log(
            "Serey category selector "
            "not found."
        )

        log(
            "Category will be skipped."
        )

        return True

    page.wait_for_timeout(1000)

    # First try exact Steemit category
    if click_exact_text(
        page,
        steem_category
    ):

        log(
            f"Category selected: "
            f"{steem_category}"
        )

        return True

    # Try case-insensitive visible text
    wanted = normalize(
        steem_category
    )

    for text in visible_texts(page):

        if normalize(text) == wanted:

            if click_exact_text(
                page,
                text
            ):

                log(
                    f"Category selected: "
                    f"{text}"
                )

                return True

    log(
        f"Serey does not appear to have "
        f"category '{steem_category}'."
    )

    # Close dropdown if possible
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    log(
        "Continuing WITHOUT category."
    )

    return True


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(
    page,
    steem_category
):

    selectors = [
        'text="Select sub category"',
        '[placeholder*="Select sub category" i]',
        '[aria-label*="sub category" i]'
    ]

    control = None

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            count = min(
                loc.count(),
                20
            )

            for i in range(count):

                try:

                    item = loc.nth(i)

                    if item.is_visible(
                        timeout=300
                    ):

                        control = item
                        break

                except Exception:
                    pass

            if control:
                break

        except Exception:
            pass

    if not control:

        log(
            "No Sub Category selector "
            "available. Skipping."
        )

        return True

    try:

        control.click(
            force=True,
            timeout=5000
        )

        page.wait_for_timeout(800)

    except Exception:

        log(
            "Could not open Sub Category. "
            "Skipping."
        )

        return True

    # Try matching Steemit category
    if steem_category:

        if click_exact_text(
            page,
            steem_category
        ):

            log(
                f"Sub Category selected: "
                f"{steem_category}"
            )

            return True

    # Otherwise choose first meaningful option
    selectors = [
        "[role='option']",
        ".ant-select-item-option",
        "li"
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            count = min(
                loc.count(),
                50
            )

            for i in range(count):

                try:

                    item = loc.nth(i)

                    if not item.is_visible(
                        timeout=200
                    ):
                        continue

                    text = item.inner_text(
                        timeout=300
                    ).strip()

                    if not text:
                        continue

                    n = normalize(text)

                    if n in [
                        "select sub category",
                        "sub category"
                    ]:
                        continue

                    item.click(
                        force=True,
                        timeout=5000
                    )

                    log(
                        f"Sub Category selected: "
                        f"{text}"
                    )

                    return True

                except Exception:
                    pass

        except Exception:
            pass

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    log(
        "No usable Sub Category found. "
        "Skipping."
    )

    return True


# ============================================================
# FIND FINAL PUBLISH BUTTON SAFELY
# ============================================================

def click_final_publish(page):

    log(
        "Searching for FINAL Publish..."
    )

    # Never accept this URL as published
    if "/blog/post/new" not in page.url:

        log(
            f"Current page is already: "
            f"{page.url}"
        )

    # Give UI time to update
    page.wait_for_timeout(1500)

    candidates = []

    selectors = [
        "button",
        "[role='button']"
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            count = min(
                loc.count(),
                100
            )

            for i in range(count):

                try:

                    btn = loc.nth(i)

                    if not btn.is_visible(
                        timeout=200
                    ):
                        continue

                    text = normalize(
                        btn.inner_text(
                            timeout=300
                        )
                    )

                    if (
                        "publish" in text
                        or
                        "post to blockchain"
                        in text
                    ):

                        candidates.append(
                            btn
                        )

                except Exception:
                    pass

        except Exception:
            pass

    # Use the last suitable visible button
    for btn in reversed(candidates):

        try:

            btn.scroll_into_view_if_needed()

            page.wait_for_timeout(300)

            btn.click(
                force=True,
                timeout=7000
            )

            log(
                "FINAL PUBLISH button clicked!"
            )

            return True

        except Exception:
            pass

    log(
        "FINAL PUBLISH button NOT found."
    )

    return False


# ============================================================
# VERIFY PUBLISHED POST
# ============================================================

def verify_post(
    page,
    post
):

    title = normalize(
        post["title"]
    )

    log(
        "\nVERIFYING PUBLISHED POST..."
    )

    page.wait_for_timeout(6000)

    current_url = page.url

    log(
        f"Current URL: {current_url}"
    )

    # Never accept creation page
    if "/blog/post/new" in current_url:

        log(
            "Still on /blog/post/new."
        )

        return False

    # Direct published page
    if (
        "/authors/" in current_url
        or
        "/blog/post/" in current_url
    ):

        try:

            html = normalize(
                page.content()
            )

            if (
                title
                and
                title in html
            ):

                log(
                    f"POST VERIFIED: "
                    f"{current_url}"
                )

                return True

        except Exception:
            pass

    # Profile verification
    profiles = [
        f"{SEREY_BASE}/authors/{SEREY_LOGIN}",
        f"{SEREY_BASE}/authors/@{SEREY_LOGIN}"
    ]

    for url in profiles:

        try:

            log(
                f"Checking profile: {url}"
            )

            page.goto(
                url,
                timeout=30000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(5000)

            html = normalize(
                page.content()
            )

            if title and title in html:

                log(
                    f"POST FOUND ON PROFILE: "
                    f"{url}"
                )

                return True

        except Exception as e:

            log(
                f"Profile verification error: "
                f"{e}"
            )

    log(
        "POST VERIFICATION FAILED."
    )

    return False


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish_post(
    page,
    post
):

    log(
        "\n" + "-" * 60
    )

    log(
        f"Publishing: {post['title']}"
    )

    log(
        f"Steemit category: "
        f"{post.get('category', '')}"
    )

    try:

        # ----------------------------------------------------
        # OPEN NEW POST
        # ----------------------------------------------------

        page.goto(
            NEW_POST_URL,
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(3000)

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title_box = page.locator(
            'input[placeholder*="title" i]'
        ).first

        title_box.fill(
            post["title"]
        )

        log(
            "✓ Title filled"
        )

        # ----------------------------------------------------
        # BODY
        # ----------------------------------------------------

        body_box = page.locator(
            'div[contenteditable="true"], '
            'textarea'
        ).first

        body_box.fill(
            post["body"]
        )

        log(
            "✓ Body filled"
        )

        # ----------------------------------------------------
        # THUMBNAIL
        # ----------------------------------------------------

        if post.get("image"):

            image_file = download_image(
                post["image"]
            )

            if image_file:

                try:

                    file_input = page.locator(
                        'input[type="file"]'
                    ).first

                    if file_input.count() > 0:

                        file_input.set_input_files(
                            image_file
                        )

                        log(
                            "✓ Thumbnail uploaded"
                        )

                        page.wait_for_timeout(
                            2500
                        )

                except Exception as e:

                    log(
                        f"Thumbnail upload skipped: "
                        f"{e}"
                    )

        else:

            log(
                "No thumbnail available."
            )

        # ----------------------------------------------------
        # FIRST PUBLISH
        # ----------------------------------------------------

        first_publish = page.locator(
            'button:has-text("Publish")'
        ).first

        first_publish.click(
            force=True,
            timeout=10000
        )

        log(
            "✓ First Publish clicked"
        )

        page.wait_for_timeout(2500)

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        category = (
            post.get("category", "")
            .strip()
        )

        select_category(
            page,
            category
        )

        page.wait_for_timeout(1000)

        # ----------------------------------------------------
        # SUB CATEGORY
        # ----------------------------------------------------

        select_subcategory(
            page,
            category
        )

        page.wait_for_timeout(1000)

        # ----------------------------------------------------
        # FINAL PUBLISH
        # ----------------------------------------------------

        if not click_final_publish(page):

            log(
                "❌ Final Publish was not clicked."
            )

            return False

        # ----------------------------------------------------
        # WAIT FOR BLOCKCHAIN/PUBLISH
        # ----------------------------------------------------

        log(
            "Waiting for Serey publication..."
        )

        page.wait_for_timeout(
            15000
        )

        log(
            f"URL after Final Publish: "
            f"{page.url}"
        )

        # ----------------------------------------------------
        # VERIFY
        # ----------------------------------------------------

        if verify_post(
            page,
            post
        ):

            log(
                "\n✅ VERIFIED & CONFIRMED"
            )

            return True

        log(
            "\n❌ Publication could not be verified."
        )

        return False

    except Exception as e:

        log(
            f"\n❌ Publish error: {e}"
        )

        return False

    finally:

        if os.path.exists(
            TEMP_IMAGE
        ):

            try:
                os.remove(
                    TEMP_IMAGE
                )
            except Exception:
                pass


# ============================================================
# LOGIN
# ============================================================

def login(page):

    log(
        "\nLogging into Serey..."
    )

    try:

        page.goto(
            SEREY_BASE,
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(3000)

        login_button = page.locator(
            'a:has-text("Log in"), '
            'button:has-text("Log in"), '
            'a:has-text("Log In"), '
            'button:has-text("Log In")'
        ).first

        login_button.click(
            force=True,
            timeout=10000
        )

        page.wait_for_timeout(2500)

        username = page.locator(
            'input[placeholder*="Username" i]'
        ).first

        password = page.locator(
            'input[placeholder*="Private Key" i], '
            'input[placeholder*="Password" i]'
        ).first

        username.fill(
            SEREY_LOGIN
        )

        password.fill(
            SEREY_PASSWORD
        )

        page.locator(
            '.ant-modal-content button:has-text("Log in"), '
            '.ant-modal-content button:has-text("Log In"), '
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        ).last.click(
            force=True,
            timeout=10000
        )

        page.wait_for_timeout(6000)

        log(
            "✓ LOGGED INTO SEREY SUCCESSFULLY!"
        )

        return True

    except Exception as e:

        log(
            f"❌ Login failed: {e}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 60)

    log(
        "STEEMIT -> SEREY BENGALI SYNC"
    )

    log("=" * 60)

    synced = load_synced()

    log(
        f"Previously synced posts: "
        f"{len(synced)}"
    )

    # --------------------------------------------------------
    # FETCH
    # --------------------------------------------------------

    posts = fetch_posts()

    # --------------------------------------------------------
    # UNSYNCED
    # --------------------------------------------------------

    new_posts = [
        p for p in posts
        if post_id(p) not in synced
    ]

    log(
        f"Total posts: {len(posts)}"
    )

    log(
        f"Unsynced posts: {len(new_posts)}"
    )

    posts_to_publish = (
        new_posts[:POSTS_PER_RUN]
    )

    log(
        f"Publishing this run: "
        f"{len(posts_to_publish)}"
    )

    if not posts_to_publish:

        log(
            "No unsynced posts."
        )

        return

    # --------------------------------------------------------
    # PLAYWRIGHT
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

        if not login(page):

            browser.close()
            return

        # ----------------------------------------------------
        # PUBLISH
        # ----------------------------------------------------

        for post in posts_to_publish:

            success = publish_post(
                page,
                post
            )

            if success:

                pid = post_id(post)

                synced.add(pid)

                save_synced(
                    synced
                )

                log(
                    f"✓ Saved as synced: {pid}"
                )

            else:

                log(
                    "\n⚠️ NOT SAVED AS SYNCED."
                )

                log(
                    "This post will retry "
                    "on the next run."
                )

        browser.close()

    log("=" * 60)

    log(
        "SYNC COMPLETED"
    )

    log("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
