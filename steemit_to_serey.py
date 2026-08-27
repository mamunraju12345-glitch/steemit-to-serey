import os
import json
import requests
import time
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

# Pexels API key from GitHub Actions Secret
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

DATA_FILE = "synced_posts.json"

# Only one post per GitHub Actions run
POSTS_PER_RUN = 1

# Historical safety limit
MAX_POSTS = 6000

# Number of image candidates to inspect
MAX_STEEM_IMAGES = 15

# Verification attempts
VERIFY_ATTEMPTS = 5

# Wait between verification attempts
VERIFY_WAIT_SECONDS = 5


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
            print(f"Trying Steem RPC: {node}", flush=True)

            response = requests.post(
                node,
                json=payload,
                headers={"Content-Type": "application/json"},
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
                f"RPC failed: {type(e).__name__}: {e}",
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
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return set(data)

        return set()

    except Exception as e:
        print(
            f"Could not read {DATA_FILE}: {e}",
            flush=True
        )
        return set()


def save_synced_posts(posts):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                sorted(posts),
                file,
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:
        print(
            f"Could not save synced posts: {e}",
            flush=True
        )


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def extract_image_urls(body_text, metadata_string):
    """
    Collect possible Steemit image URLs.

    We keep multiple candidates because old Steemit posts
    may contain several images and some old hosts may be dead.
    """

    urls = []

    # --------------------------------------------------------
    # JSON metadata
    # --------------------------------------------------------

    try:
        meta = json.loads(metadata_string)

        if isinstance(meta, dict):

            image_list = meta.get("image", [])

            if isinstance(image_list, list):
                for url in image_list:
                    if isinstance(url, str):
                        if url.startswith("http"):
                            urls.append(url)

    except Exception:
        pass

    # --------------------------------------------------------
    # Markdown images
    # --------------------------------------------------------

    markdown_images = re.findall(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        body_text,
        flags=re.IGNORECASE
    )

    urls.extend(markdown_images)

    # --------------------------------------------------------
    # Normal URLs
    # --------------------------------------------------------

    normal_urls = re.findall(
        r'https?://[^\s<>"\']+',
        body_text,
        flags=re.IGNORECASE
    )

    for url in normal_urls:

        clean_url = url.rstrip(
            '.,;:!?)]}'
        )

        lower_url = clean_url.lower()

        if any(
            extension in lower_url
            for extension in [
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".webp"
            ]
        ):
            urls.append(clean_url)

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique = []

    for url in urls:
        if url not in unique:
            unique.append(url)

    return unique


def clean_body(body_text):
    """
    Remove markdown image lines and direct image URLs.
    """

    body = body_text

    # Remove markdown image syntax
    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    # Remove image URLs
    body = re.sub(
        r'https?://\S+\.(?:png|jpg|jpeg|gif|webp)(?:\?\S*)?',
        '',
        body,
        flags=re.IGNORECASE
    )

    # Remove excessive empty lines
    body = re.sub(
        r'\n\s*\n\s*\n+',
        '\n\n',
        body
    )

    return body.strip()


# ============================================================
# FETCH ALL STEEM POSTS
# ============================================================

def get_all_posts():
    print(
        f"Fetching ALL historical posts from Steemit: "
        f"@{STEEM_USERNAME}",
        flush=True
    )

    all_posts = []
    seen_permlinks = set()

    start_author = None
    start_permlink = None

    batch_number = 0

    while True:

        batch_number += 1

        print(
            f"Fetching Steemit batch #{batch_number}...",
            flush=True
        )

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author and start_permlink:
            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

        try:
            result = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                params
            )

        except Exception as e:

            print(
                f"Batch #{batch_number} failed: {e}",
                flush=True
            )

            # Retry same batch
            batch_number -= 1

            time.sleep(3)

            continue

        if not result:
            print(
                "No more Steemit posts returned.",
                flush=True
            )
            break

        # First request returns normal batch.
        # Following requests overlap one item, so skip first item.
        if start_author and start_permlink:
            batch = result[1:]
        else:
            batch = result

        if not batch:
            break

        new_count = 0

        for post in batch:

            if post.get("author") != STEEM_USERNAME:
                continue

            permlink = post.get("permlink")

            if not permlink:
                continue

            if permlink in seen_permlinks:
                continue

            seen_permlinks.add(permlink)

            raw_body = post.get("body", "")

            metadata = post.get(
                "json_metadata",
                "{}"
            )

            image_urls = extract_image_urls(
                raw_body,
                metadata
            )

            clean_content = clean_body(
                raw_body
            )

            all_posts.append(
                {
                    "author": post.get(
                        "author",
                        STEEM_USERNAME
                    ),
                    "permlink": permlink,
                    "title": post.get(
                        "title",
                        ""
                    ),
                    "body": clean_content,
                    "image_urls": image_urls,
                    "category": post.get(
                        "category",
                        ""
                    ),
                    "created": post.get(
                        "created",
                        ""
                    )
                }
            )

            new_count += 1

        print(
            f"Batch #{batch_number}: "
            f"{len(result)} received, "
            f"{new_count} new posts. "
            f"Total: {len(all_posts)}",
            flush=True
        )

        # ----------------------------------------------------
        # Safety limit
        # ----------------------------------------------------

        if len(all_posts) >= MAX_POSTS:

            print(
                f"Reached {MAX_POSTS}-post safety limit.",
                flush=True
            )

            break

        # ----------------------------------------------------
        # Pagination
        # ----------------------------------------------------

        last_post = result[-1]

        new_start_author = last_post.get(
            "author"
        )

        new_start_permlink = last_post.get(
            "permlink"
        )

        if (
            new_start_author == start_author
            and
            new_start_permlink == start_permlink
        ):
            break

        start_author = new_start_author
        start_permlink = new_start_permlink

        if len(result) < 100:
            break

        time.sleep(0.5)

    # Oldest first
    all_posts.reverse()

    return all_posts


# ============================================================
# DOWNLOAD STEEMIT IMAGE
# ============================================================

def download_image(url, output_path):
    """
    Try to download a Steemit image.
    """

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/122.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,"
                      "image/svg+xml,image/*,*/*;q=0.8"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=25,
            allow_redirects=True
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type",
            ""
        ).lower()

        if not content_type.startswith("image/"):

            # Some old servers don't send proper content-type.
            if len(response.content) < 1000:
                raise RuntimeError(
                    "Downloaded content is not a valid image."
                )

        with open(
            output_path,
            "wb"
        ) as file:
            file.write(response.content)

        if os.path.getsize(output_path) < 1000:

            os.remove(output_path)

            raise RuntimeError(
                "Downloaded image is too small."
            )

        return True

    except Exception as e:

        print(
            f"Image download failed: {e}",
            flush=True
        )

        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        return False


# ============================================================
# PEXELS SEARCH
# ============================================================

def make_pexels_query(title, body):
    """
    Create a simple English-oriented search query.

    Pexels supports locale parameters, but English keywords
    generally provide broader stock-photo results.
    """

    text = f"{title} {body}"

    text = re.sub(
        r'[^A-Za-z0-9\s]',
        ' ',
        text
    )

    words = text.lower().split()

    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "about",
        "your",
        "have",
        "has",
        "was",
        "were",
        "are",
        "you",
        "our",
        "their",
        "they",
        "into",
        "then",
        "than",
        "will",
        "would",
        "could",
        "should",
        "some",
        "very",
        "more",
        "also",
        "just",
        "like",
        "what",
        "when",
        "where",
        "which",
        "while",
        "been",
        "being"
    }

    filtered = []

    for word in words:

        if len(word) < 3:
            continue

        if word in stop_words:
            continue

        if word not in filtered:
            filtered.append(word)

    # Prefer first 5 meaningful words
    query = " ".join(filtered[:5])

    if not query:
        query = "nature landscape"

    return query


def search_pexels_image(
    title,
    body,
    output_path
):
    """
    Search Pexels and download the first usable
    landscape photo.
    """

    if not PEXELS_API_KEY:

        print(
            "❌ PEXELS_API_KEY not found.",
            flush=True
        )

        return None

    query = make_pexels_query(
        title,
        body
    )

    print(
        f"🔎 Pexels search query: {query}",
        flush=True
    )

    endpoint = (
        "https://api.pexels.com/v1/search"
    )

    headers = {
        "Authorization": PEXELS_API_KEY,
        "User-Agent": "Steemit-to-Serey-Automation"
    }

    params = {
        "query": query,
        "orientation": "landscape",
        "size": "large",
        "locale": "en-US",
        "page": 1,
        "per_page": 10
    }

    try:

        response = requests.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:

            print(
                f"❌ Pexels API error: "
                f"HTTP {response.status_code}",
                flush=True
            )

            try:
                print(
                    response.text[:500],
                    flush=True
                )
            except Exception:
                pass

            return None

        data = response.json()

        photos = data.get(
            "photos",
            []
        )

        if not photos:

            print(
                "❌ No Pexels photos found.",
                flush=True
            )

            return None

        for index, photo in enumerate(
            photos,
            start=1
        ):

            src = photo.get(
                "src",
                {}
            )

            image_url = (
                src.get("large2x")
                or
                src.get("large")
                or
                src.get("landscape")
                or
                src.get("original")
            )

            if not image_url:
                continue

            print(
                f"Trying Pexels image {index}: "
                f"{image_url}",
                flush=True
            )

            if download_image(
                image_url,
                output_path
            ):

                photographer = photo.get(
                    "photographer",
                    "Unknown"
                )

                pexels_page = photo.get(
                    "url",
                    "https://www.pexels.com/"
                )

                print(
                    "✅ Pexels image downloaded.",
                    flush=True
                )

                print(
                    f"   Photographer: {photographer}",
                    flush=True
                )

                print(
                    f"   Photo page: {pexels_page}",
                    flush=True
                )

                return {
                    "path": output_path,
                    "photographer": photographer,
                    "url": pexels_page
                }

    except Exception as e:

        print(
            f"❌ Pexels request failed: {e}",
            flush=True
        )

    return None


# ============================================================
# GET BEST IMAGE
# ============================================================

def get_best_image(post):
    """
    Priority:
    1. Steemit image
    2. Pexels fallback
    3. No image
    """

    temp_path = "temp_thumbnail.jpg"

    # Remove previous temporary image
    if os.path.exists(temp_path):

        try:
            os.remove(temp_path)
        except Exception:
            pass

    # --------------------------------------------------------
    # 1. STEEMIT IMAGE
    # --------------------------------------------------------

    image_urls = post.get(
        "image_urls",
        []
    )

    if image_urls:

        print(
            f"Found {len(image_urls)} "
            f"Steemit image candidate(s).",
            flush=True
        )

        candidates = image_urls[
            :MAX_STEEM_IMAGES
        ]

        for index, url in enumerate(
            candidates,
            start=1
        ):

            print(
                f"Trying Steemit image {index}: "
                f"{url}",
                flush=True
            )

            # Try twice
            for attempt in range(
                1,
                3
            ):

                print(
                    f"Image attempt {attempt}...",
                    flush=True
                )

                if download_image(
                    url,
                    temp_path
                ):

                    print(
                        "✅ Steemit image downloaded "
                        "successfully!",
                        flush=True
                    )

                    return {
                        "path": temp_path,
                        "source": "steemit",
                        "url": url
                    }

                time.sleep(1)

        print(
            "❌ No working Steemit image found.",
            flush=True
        )

    else:

        print(
            "⚠️ No Steemit image found.",
            flush=True
        )

    # --------------------------------------------------------
    # 2. PEXELS FALLBACK
    # --------------------------------------------------------

    print(
        "🔄 Trying Pexels fallback...",
        flush=True
    )

    pexels_result = search_pexels_image(
        post.get("title", ""),
        post.get("body", ""),
        temp_path
    )

    if pexels_result:

        return {
            "path": pexels_result["path"],
            "source": "pexels",
            "url": pexels_result["url"],
            "photographer": pexels_result[
                "photographer"
            ]
        }

    # --------------------------------------------------------
    # 3. NO IMAGE
    # --------------------------------------------------------

    print(
        "⚠️ No thumbnail available.",
        flush=True
    )

    return None


# ============================================================
# SEREY VERIFICATION
# ============================================================

def normalize_text(text):
    """
    Normalize text for title comparison.
    """

    if not text:
        return ""

    text = text.lower()

    text = re.sub(
        r'\s+',
        ' ',
        text
    )

    return text.strip()


def title_found_on_page(
    page,
    expected_title
):
    """
    Search title in page HTML and visible text.
    """

    expected = normalize_text(
        expected_title
    )

    if not expected:
        return False

    try:

        html = page.content()

        normalized_html = normalize_text(
            re.sub(
                r'<[^>]+>',
                ' ',
                html
            )
        )

        if expected in normalized_html:
            return True

        # Also check shorter meaningful title
        words = expected.split()

        if len(words) >= 4:

            partial = " ".join(
                words[:4]
            )

            if partial in normalized_html:
                return True

    except Exception:
        pass

    return False


def verify_serey_post(
    page,
    post
):
    """
    Verify the newly published Serey post.

    We first check current page.
    Then try to discover the profile.
    """

    title = post.get(
        "title",
        ""
    )

    username = SEREY_LOGIN

    print(
        "🔎 VERIFYING POST ON SEREY...",
        flush=True
    )

    print(
        f"Expected title: {title}",
        flush=True
    )

    # --------------------------------------------------------
    # 1. Check current page
    # --------------------------------------------------------

    current_url = page.url

    print(
        f"Current Serey URL: {current_url}",
        flush=True
    )

    if title_found_on_page(
        page,
        title
    ):

        print(
            "✅ TITLE FOUND ON CURRENT SEREY PAGE!",
            flush=True
        )

        return True

    # --------------------------------------------------------
    # 2. Try author profile
    # --------------------------------------------------------

    profile_urls = [
        f"https://serey.io/authors/{username}",
        f"https://serey.io/authors/@{username}"
    ]

    for attempt in range(
        1,
        VERIFY_ATTEMPTS + 1
    ):

        print(
            f"Verification attempt "
            f"{attempt}/{VERIFY_ATTEMPTS}",
            flush=True
        )

        for profile_url in profile_urls:

            try:

                print(
                    f"Checking: {profile_url}",
                    flush=True
                )

                page.goto(
                    profile_url,
                    timeout=30000,
                    wait_until="domcontentloaded"
                )

                page.wait_for_timeout(
                    VERIFY_WAIT_SECONDS * 1000
                )

                if title_found_on_page(
                    page,
                    title
                ):

                    print(
                        "✅ TITLE FOUND ON "
                        "SEREY PROFILE!",
                        flush=True
                    )

                    print(
                        f"Verified URL: {page.url}",
                        flush=True
                    )

                    return True

            except Exception as e:

                print(
                    f"Verification page error: {e}",
                    flush=True
                )

        # ----------------------------------------------------
        # 3. Search current page again
        # ----------------------------------------------------

        try:

            if title_found_on_page(
                page,
                title
            ):

                print(
                    "✅ POST VERIFIED!",
                    flush=True
                )

                return True

        except Exception:
            pass

        if attempt < VERIFY_ATTEMPTS:

            print(
                "⏳ Post may still be propagating. "
                f"Waiting {VERIFY_WAIT_SECONDS}s...",
                flush=True
            )

            time.sleep(
                VERIFY_WAIT_SECONDS
            )

    print(
        "❌ POST COULD NOT BE VERIFIED ON SEREY.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH TO SEREY
# ============================================================

def publish_to_serey(
    page,
    post
):
    print(
        f"\n---> Publishing to Serey: "
        f"{post['title']}",
        flush=True
    )

    image_info = None

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

        title_box = page.locator(
            'input[placeholder*="title" i], '
            'input[placeholder*="Title"]'
        ).first

        title_box.wait_for(
            state="visible",
            timeout=20000
        )

        title_box.fill(
            post["title"]
        )

        print(
            "  - Title filled!",
            flush=True
        )

        # ----------------------------------------------------
        # BODY
        # ----------------------------------------------------

        body_box = page.locator(
            'div[contenteditable="true"], '
            'textarea[placeholder*="content" i], '
            'textarea'
        ).first

        body_box.wait_for(
            state="visible",
            timeout=20000
        )

        body_box.fill(
            post["body"]
        )

        print(
            "  - Clean body content filled!",
            flush=True
        )

        page.wait_for_timeout(1500)

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        image_info = get_best_image(
            post
        )

        if image_info:

            try:

                file_input = page.locator(
                    'input[type="file"]'
                ).first

                if file_input.count() > 0:

                    file_input.set_input_files(
                        image_info["path"]
                    )

                    print(
                        "  - Thumbnail image "
                        "uploaded!",
                        flush=True
                    )

                    page.wait_for_timeout(
                        4000
                    )

                    if image_info.get(
                        "source"
                    ) == "pexels":

                        print(
                            "  - Image source: "
                            "Pexels",
                            flush=True
                        )

                        print(
                            "  - Photographer: "
                            f"{image_info.get('photographer', 'Unknown')}",
                            flush=True
                        )

                else:

                    print(
                        "⚠️ Serey file input "
                        "not found.",
                        flush=True
                    )

            except Exception as e:

                print(
                    f"⚠️ Thumbnail upload failed: "
                    f"{e}",
                    flush=True
                )

        else:

            print(
                "⚠️ Publishing without image.",
                flush=True
            )

        # ----------------------------------------------------
        # FIRST PUBLISH
        # ----------------------------------------------------

        publish_buttons = page.locator(
            'button:has-text("Publish")'
        )

        if publish_buttons.count() == 0:

            raise RuntimeError(
                "First Publish button not found."
            )

        publish_buttons.first.click(
            force=True
        )

        print(
            "  - First Publish button clicked!",
            flush=True
        )

        # Wait for category modal
        page.wait_for_timeout(
            6000
        )

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        category_selected = False

        try:

            dropdown = page.locator(
                'div:has-text("Select category"), '
                '.ant-select, '
                'input[placeholder*="category" i]'
            ).first

            if dropdown.count() > 0:

                dropdown.click(
                    force=True
                )

                page.wait_for_timeout(
                    1500
                )

                # Prefer General
                options = page.locator(
                    'div[title="General"], '
                    'div[title="general"], '
                    '.ant-select-item-option'
                )

                if options.count() > 0:

                    options.first.click(
                        force=True
                    )

                    category_selected = True

            if not category_selected:

                page.keyboard.press(
                    "ArrowDown"
                )

                page.keyboard.press(
                    "Enter"
                )

                category_selected = True

            print(
                "  - Category selected!",
                flush=True
            )

        except Exception as e:

            print(
                f"  - Category selector "
                f"fallback: {e}",
                flush=True
            )

            try:

                page.keyboard.press(
                    "Tab"
                )

                page.keyboard.press(
                    "ArrowDown"
                )

                page.keyboard.press(
                    "Enter"
                )

                print(
                    "  - Category selected "
                    "via keyboard!",
                    flush=True
                )

            except Exception:
                pass

        page.wait_for_timeout(
            2000
        )

        # ----------------------------------------------------
        # FINAL PUBLISH
        # ----------------------------------------------------

        final_publish = page.locator(
            '.ant-modal-content '
            'button:has-text("Publish"), '
            '.ant-modal-footer '
            'button:has-text("Publish"), '
            'button:has-text("Publish")'
        ).last

        if final_publish.count() == 0:

            raise RuntimeError(
                "Final Publish button not found."
            )

        final_publish.click(
            force=True
        )

        print(
            "  - Final Publish button clicked!",
            flush=True
        )

        # Give Serey time to broadcast/save
        page.wait_for_timeout(
            10000
        )

        # ----------------------------------------------------
        # VERIFICATION
        # ----------------------------------------------------

        verified = verify_serey_post(
            page,
            post
        )

        # ----------------------------------------------------
        # CLEAN TEMP IMAGE
        # ----------------------------------------------------

        if os.path.exists(
            "temp_thumbnail.jpg"
        ):

            try:
                os.remove(
                    "temp_thumbnail.jpg"
                )
            except Exception:
                pass

        if verified:

            print(
                f"✅ VERIFIED & CONFIRMED: "
                f"{post['title']}",
                flush=True
            )

            return True

        print(
            "⚠️ Verification failed. "
            "Post will NOT be saved as synced.",
            flush=True
        )

        return False

    except Exception as e:

        if os.path.exists(
            "temp_thumbnail.jpg"
        ):

            try:
                os.remove(
                    "temp_thumbnail.jpg"
                )
            except Exception:
                pass

        print(
            f"❌ Failed to publish post on Serey: "
            f"{e}",
            flush=True
        )

        return False


# ============================================================
# LOGIN
# ============================================================

def login_to_serey(page):
    print(
        "\nLogging into Serey.io...",
        flush=True
    )

    try:

        page.goto(
            "https://serey.io",
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            4000
        )

        print(
            "Clicking Log in button...",
            flush=True
        )

        login_button = page.locator(
            'a:has-text("Log in"), '
            'button:has-text("Log in"), '
            'a:has-text("Log In"), '
            'button:has-text("Log In")'
        ).first

        login_button.click(
            force=True
        )

        page.wait_for_timeout(
            4000
        )

        page.wait_for_selector(
            'input[placeholder="Username"], '
            'input[placeholder*="Username"]',
            timeout=20000
        )

        username_box = page.locator(
            'input[placeholder="Username"], '
            'input[placeholder*="Username"]'
        ).first

        username_box.fill(
            SEREY_LOGIN
        )

        password_box = page.locator(
            'input[placeholder*="Private Key or Password"], '
            'input[placeholder*="Private Key"], '
            'input[type="password"]'
        ).first

        password_box.fill(
            SEREY_PASSWORD
        )

        login_submit = page.locator(
            '.ant-modal-content '
            'button:has-text("Log in"), '
            '.ant-modal-content '
            'button:has-text("Log In"), '
            'button:has-text("Log in")'
        ).last

        login_submit.click(
            force=True
        )

        page.wait_for_timeout(
            7000
        )

        print(
            "✅ LOGGED INTO SEREY SUCCESSFULLY!",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"❌ Login failed: {e}",
            flush=True
        )

        return False


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

    # --------------------------------------------------------
    # Validate environment
    # --------------------------------------------------------

    if not STEEM_USERNAME:

        print(
            "❌ STEEM_USERNAME is missing.",
            flush=True
        )

        return

    if not SEREY_LOGIN:

        print(
            "❌ SEREY_LOGIN is missing.",
            flush=True
        )

        return

    if not SEREY_PASSWORD:

        print(
            "❌ SEREY_PASSWORD is missing.",
            flush=True
        )

        return

    if PEXELS_API_KEY:

        print(
            "✅ PEXELS_API_KEY detected.",
            flush=True
        )

    else:

        print(
            "⚠️ PEXELS_API_KEY not detected. "
            "Pexels fallback will be unavailable.",
            flush=True
        )

    # --------------------------------------------------------
    # Load synced
    # --------------------------------------------------------

    synced_posts = load_synced_posts()

    print(
        f"Previously synced posts: "
        f"{len(synced_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # Fetch posts
    # --------------------------------------------------------

    posts = get_all_posts()

    print(
        f"Total historical posts fetched: "
        f"{len(posts)}",
        flush=True
    )

    print(
        f"Total posts fetched: "
        f"{len(posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # Find unsynced
    # --------------------------------------------------------

    new_posts = []

    for post in posts:

        post_id = (
            f"{post['author']}/"
            f"{post['permlink']}"
        )

        if post_id not in synced_posts:

            new_posts.append(
                post
            )

    print(
        f"Unsynced posts available: "
        f"{len(new_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # One post per run
    # --------------------------------------------------------

    posts_to_publish = new_posts[
        :POSTS_PER_RUN
    ]

    print(
        f"Publishing this run: "
        f"{len(posts_to_publish)} post(s)",
        flush=True
    )

    if not posts_to_publish:

        print(
            "No new posts to sync!",
            flush=True
        )

        return

    # --------------------------------------------------------
    # Browser
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

        if not login_to_serey(page):

            browser.close()

            return

        # ----------------------------------------------------
        # PUBLISH
        # ----------------------------------------------------

        for post in posts_to_publish:

            success = publish_to_serey(
                page,
                post
            )

            post_id = (
                f"{post['author']}/"
                f"{post['permlink']}"
            )

            if success:

                synced_posts.add(
                    post_id
                )

                save_synced_posts(
                    synced_posts
                )

                print(
                    f"✅ Saved as synced: "
                    f"{post_id}",
                    flush=True
                )

            else:

                print(
                    f"⚠️ NOT saved as synced: "
                    f"{post_id}",
                    flush=True
                )

        # ----------------------------------------------------
        # CLOSE
        # ----------------------------------------------------

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


if __name__ == "__main__":
    main()
