import os
import json
import requests
import time
import re
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"].strip()

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()

PEXELS_API_KEY = os.environ.get(
    "PEXELS_API_KEY",
    ""
).strip()

DATA_FILE = "synced_posts.json"

# প্রতি GitHub Actions run-এ কতটি post publish করবে
POSTS_PER_RUN = 1

# সর্বোচ্চ historical posts
MAX_POSTS = 6000

# সর্বোচ্চ Steem batches
MAX_BATCHES = 100

# Serey publish হওয়ার পর কতবার verification করবে
VERIFY_ATTEMPTS = 10

# দুই verification-এর মাঝে কত সেকেন্ড অপেক্ষা করবে
VERIFY_WAIT_SECONDS = 10

# Temporary image
TEMP_IMG_FILE = "temp_thumbnail.jpg"

# Serey
SEREY_BASE = "https://serey.io"


# ============================================================
# STEEM RPC NODES
# ============================================================

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
# COMMON HEADERS
# ============================================================

BROWSER_USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/122.0.0.0 "
    "Safari/537.36"
)


IMAGE_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "image/avif,image/webp,image/apng,"
        "image/svg+xml,image/*,*/*;q=0.8"
    ),
    "Referer": "https://steemit.com/",
}


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

            print(
                f"Trying Steem RPC: {node}",
                flush=True
            )

            response = requests.post(
                node,
                json=payload,
                headers={
                    "Content-Type": "application/json"
                },
                timeout=30
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

            print(
                f"Steem RPC failed: {node} -> {e}",
                flush=True
            )

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed. "
        f"Last error: {last_error}"
    )


# ============================================================
# SYNCED POSTS
# ============================================================

def load_synced_posts():

    if not os.path.exists(DATA_FILE):

        print(
            "synced_posts.json not found. "
            "Starting with empty sync database.",
            flush=True
        )

        return set()

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):

            return set(
                str(x)
                for x in data
            )

        print(
            "synced_posts.json format is invalid.",
            flush=True
        )

    except Exception as e:

        print(
            f"Could not read {DATA_FILE}: {e}",
            flush=True
        )

    return set()


def save_synced_posts(posts):

    try:

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

        print(
            f"Saved synced_posts.json "
            f"({len(posts)} posts)",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"Could not save synced_posts.json: {e}",
            flush=True
        )

        return False


# ============================================================
# URL HELPERS
# ============================================================

def clean_url(url):

    if not url:

        return None

    url = str(url).strip()

    url = url.rstrip(
        ".,;:!?)]}\"'"
    )

    if url.startswith("//"):

        url = "https:" + url

    return url


def is_image_url(url):

    if not url:

        return False

    url = url.lower().strip()

    if url.startswith("//"):

        url = "https:" + url

    known_hosts = [

        "steemitimages.com",
        "cdn.steemitimages.com",
        "images.steemitimages.com",

        "img.esteem.ws",

        "images.pexels.com",

        "i67.tinypic.com",
        "tinypic.com",

        "imgur.com",
        "i.imgur.com",

        "ipfs.io",
        "gateway.pinata.cloud"

    ]

    for host in known_hosts:

        if host in url:

            return True

    if re.search(
        r"\.(jpg|jpeg|png|gif|webp|bmp)(\?.*)?$",
        url,
        re.IGNORECASE
    ):

        return True

    return False


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def extract_all_images(
    body,
    metadata
):

    images = []

    # --------------------------------------------------------
    # JSON metadata
    # --------------------------------------------------------

    try:

        if isinstance(
            metadata,
            str
        ):

            meta = json.loads(
                metadata
            )

        elif isinstance(
            metadata,
            dict
        ):

            meta = metadata

        else:

            meta = {}

        if isinstance(
            meta,
            dict
        ):

            meta_images = meta.get(
                "image",
                []
            )

            if isinstance(
                meta_images,
                list
            ):

                for img in meta_images:

                    if not isinstance(
                        img,
                        str
                    ):

                        continue

                    img = clean_url(
                        img
                    )

                    if (
                        img
                        and
                        img not in images
                    ):

                        images.append(
                            img
                        )

    except Exception as e:

        print(
            f"Metadata image extraction warning: {e}",
            flush=True
        )

    # --------------------------------------------------------
    # Markdown images
    # --------------------------------------------------------

    markdown_images = re.findall(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        body or "",
        re.IGNORECASE
    )

    for img in markdown_images:

        img = clean_url(
            img
        )

        if (
            img
            and
            img not in images
        ):

            images.append(
                img
            )

    # --------------------------------------------------------
    # Raw image URLs
    # --------------------------------------------------------

    raw_urls = re.findall(
        r'https?://[^\s<>"\']+',
        body or "",
        re.IGNORECASE
    )

    for url in raw_urls:

        url = clean_url(
            url
        )

        if (
            is_image_url(url)
            and
            url not in images
        ):

            images.append(
                url
            )

    return images


# ============================================================
# CLEAN BODY
# ============================================================

def extract_image_and_clean_body(
    body_text,
    json_metadata_str
):

    body_text = body_text or ""

    images = extract_all_images(
        body_text,
        json_metadata_str
    )

    first_image = (
        images[0]
        if images
        else None
    )

    clean_body = body_text

    # Remove markdown images
    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )

    # Remove image URLs
    body_images = extract_all_images(
        body_text,
        "{}"
    )

    for url in body_images:

        clean_body = clean_body.replace(
            url,
            ""
        )

    # Remove excessive blank lines
    clean_body = re.sub(
        r'\n[ \t]*\n[ \t]*\n+',
        '\n\n',
        clean_body
    )

    return (
        first_image,
        images,
        clean_body.strip()
    )


# ============================================================
# FETCH ALL STEEM POSTS
# ============================================================

def get_recent_posts():

    print(
        f"\nFetching ALL historical posts from "
        f"Steemit: @{STEEM_USERNAME}",
        flush=True
    )

    all_posts = []

    seen_posts = set()

    start_author = None
    start_permlink = None

    batch_number = 0

    while batch_number < MAX_BATCHES:

        batch_number += 1

        print(
            f"Fetching Steemit batch #{batch_number}...",
            flush=True
        )

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if (
            start_author
            and
            start_permlink
        ):

            params["start_author"] = (
                start_author
            )

            params["start_permlink"] = (
                start_permlink
            )

        try:

            result = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                params
            )

        except Exception as e:

            print(
                f"Failed to fetch batch "
                f"#{batch_number}: {e}",
                flush=True
            )

            break

        if not result:

            print(
                "No more Steemit posts.",
                flush=True
            )

            break

        if (
            start_author
            and
            start_permlink
        ):

            batch = result[1:]

        else:

            batch = result

        if not batch:

            print(
                "No new posts in this batch.",
                flush=True
            )

            break

        added = 0

        for post in batch:

            if post.get(
                "author"
            ) != STEEM_USERNAME:

                continue

            author = post.get(
                "author",
                ""
            )

            permlink = post.get(
                "permlink",
                ""
            )

            if not permlink:

                continue

            post_id = (
                f"{author}/{permlink}"
            )

            if post_id in seen_posts:

                continue

            seen_posts.add(
                post_id
            )

            raw_body = post.get(
                "body",
                ""
            )

            metadata = post.get(
                "json_metadata",
                "{}"
            )

            (
                image_url,
                image_candidates,
                clean_body
            ) = extract_image_and_clean_body(
                raw_body,
                metadata
            )

            all_posts.append({

                "author": author,

                "permlink": permlink,

                "title": post.get(
                    "title",
                    ""
                ),

                "body": clean_body,

                "raw_body": raw_body,

                "image": image_url,

                "image_candidates":
                    image_candidates,

                "category": post.get(
                    "category",
                    ""
                ),

                "created": post.get(
                    "created",
                    ""
                )

            })

            added += 1

        print(
            f"Batch #{batch_number}: "
            f"{len(result)} received, "
            f"{added} new posts. "
            f"Total: {len(all_posts)}",
            flush=True
        )

        last_post = result[-1]

        new_start_author = (
            last_post.get(
                "author"
            )
        )

        new_start_permlink = (
            last_post.get(
                "permlink"
            )
        )

        if (
            new_start_author
            == start_author
            and
            new_start_permlink
            == start_permlink
        ):

            print(
                "Pagination cursor did not change. "
                "Stopping safely.",
                flush=True
            )

            break

        start_author = (
            new_start_author
        )

        start_permlink = (
            new_start_permlink
        )

        if len(all_posts) >= MAX_POSTS:

            print(
                f"Reached MAX_POSTS={MAX_POSTS}.",
                flush=True
            )

            break

        if len(result) < 100:

            print(
                "Last batch contains fewer "
                "than 100 posts.",
                flush=True
            )

            break

        time.sleep(0.3)

    # Oldest -> newest
    all_posts.reverse()

    print(
        f"\nTotal historical posts fetched: "
        f"{len(all_posts)}",
        flush=True
    )

    return all_posts


# ============================================================
# IMAGE DOWNLOAD
# ============================================================

def download_image(
    url,
    output_path
):

    if not url:

        return False

    try:

        print(
            f"Downloading image: {url}",
            flush=True
        )

        response = requests.get(
            url,
            headers=IMAGE_HEADERS,
            timeout=30,
            allow_redirects=True
        )

        response.raise_for_status()

        content_type = (
            response.headers.get(
                "Content-Type",
                ""
            )
            .lower()
        )

        data = response.content

        if len(data) < 1000:

            raise RuntimeError(
                "Downloaded file is too small."
            )

        if "text/html" in content_type:

            raise RuntimeError(
                "Server returned HTML "
                "instead of an image."
            )

        with open(
            output_path,
            "wb"
        ) as f:

            f.write(data)

        print(
            "✅ Image downloaded successfully.",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"Image download failed: {e}",
            flush=True
        )

        return False


# ============================================================
# FIND WORKING STEEMIT IMAGE
# ============================================================

def find_working_steemit_image(
    post,
    output_path
):

    candidates = []

    if post.get("image"):

        candidates.append(
            post["image"]
        )

    for image in post.get(
        "image_candidates",
        []
    ):

        if image not in candidates:

            candidates.append(
                image
            )

    print(
        f"Found {len(candidates)} "
        f"Steemit image candidate(s).",
        flush=True
    )

    if not candidates:

        return None

    for index, url in enumerate(
        candidates,
        start=1
    ):

        print(
            f"Trying Steemit image "
            f"{index}: {url}",
            flush=True
        )

        for attempt in range(
            1,
            3
        ):

            print(
                f"Image attempt {attempt}/2",
                flush=True
            )

            if download_image(
                url,
                output_path
            ):

                return url

            time.sleep(1)

    print(
        "❌ No working Steemit image found.",
        flush=True
    )

    return None


# ============================================================
# PEXELS SEARCH QUERIES
# ============================================================

def build_pexels_queries(
    post
):

    title = post.get(
        "title",
        ""
    ).strip()

    clean_title = re.sub(
        r"[^A-Za-z0-9\u0980-\u09FF\u0600-\u06FF\s]",
        " ",
        title
    )

    clean_title = re.sub(
        r"\s+",
        " ",
        clean_title
    ).strip()

    queries = []

    if clean_title:

        queries.append(
            clean_title[:100]
        )

    words = clean_title.split()

    if len(words) >= 4:

        queries.append(
            " ".join(
                words[:6]
            )
        )

    if len(words) >= 2:

        queries.append(
            " ".join(
                words[:3]
            )
        )

    # English fallback queries
    queries.extend([
        "people",
        "life",
        "story",
        "travel",
        "world",
        "lifestyle",
        "technology"
    ])

    result = []

    for q in queries:

        q = q.strip()

        if not q:

            continue

        if q.lower() not in [
            x.lower()
            for x in result
        ]:

            result.append(q)

    return result


# ============================================================
# PEXELS FALLBACK
# ============================================================

def get_pexels_image(
    post,
    output_path
):

    print(
        "\n🔄 Trying Pexels fallback...",
        flush=True
    )

    if not PEXELS_API_KEY:

        print(
            "⚠️ PEXELS_API_KEY not configured.",
            flush=True
        )

        return None

    endpoint = (
        "https://api.pexels.com/v1/search"
    )

    headers = {
        "Authorization":
            PEXELS_API_KEY
    }

    queries = build_pexels_queries(
        post
    )

    for query in queries:

        print(
            f"🔎 Pexels query: {query}",
            flush=True
        )

        try:

            response = requests.get(
                endpoint,
                headers=headers,
                params={
                    "query": query,
                    "per_page": 5,
                    "orientation": "landscape"
                },
                timeout=30
            )

            if response.status_code != 200:

                print(
                    f"Pexels API error: "
                    f"{response.status_code}",
                    flush=True
                )

                continue

            data = response.json()

            photos = data.get(
                "photos",
                []
            )

            if not photos:

                continue

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
                    src.get("original")
                )

                if not image_url:

                    continue

                print(
                    f"Trying Pexels image "
                    f"{index}: {image_url}",
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

                    photo_page = photo.get(
                        "url",
                        ""
                    )

                    print(
                        "✅ Pexels image downloaded.",
                        flush=True
                    )

                    print(
                        f"Photographer: "
                        f"{photographer}",
                        flush=True
                    )

                    print(
                        f"Photo page: "
                        f"{photo_page}",
                        flush=True
                    )

                    return {

                        "source":
                            "Pexels",

                        "image_url":
                            image_url,

                        "photographer":
                            photographer,

                        "photo_page":
                            photo_page

                    }

        except Exception as e:

            print(
                f"Pexels request failed: {e}",
                flush=True
            )

        time.sleep(1)

    print(
        "❌ No Pexels image found.",
        flush=True
    )

    return None


# ============================================================
# PREPARE THUMBNAIL
# ============================================================

def prepare_thumbnail(
    post
):

    if os.path.exists(
        TEMP_IMG_FILE
    ):

        try:

            os.remove(
                TEMP_IMG_FILE
            )

        except Exception:

            pass

    # --------------------------------------------------------
    # 1. STEEMIT IMAGE
    # --------------------------------------------------------

    print(
        "\n🖼️ Searching for Steemit image...",
        flush=True
    )

    steemit_image = (
        find_working_steemit_image(
            post,
            TEMP_IMG_FILE
        )
    )

    if steemit_image:

        return {

            "path":
                TEMP_IMG_FILE,

            "source":
                "Steemit",

            "url":
                steemit_image,

            "photographer":
                "",

            "photo_page":
                ""

        }

    # --------------------------------------------------------
    # 2. PEXELS
    # --------------------------------------------------------

    pexels_result = (
        get_pexels_image(
            post,
            TEMP_IMG_FILE
        )
    )

    if pexels_result:

        return {

            "path":
                TEMP_IMG_FILE,

            "source":
                "Pexels",

            "url":
                pexels_result[
                    "image_url"
                ],

            "photographer":
                pexels_result[
                    "photographer"
                ],

            "photo_page":
                pexels_result[
                    "photo_page"
                ]

        }

    return None


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(
    text
):

    if not text:

        return ""

    text = str(text).lower()

    # HTML entities / whitespace
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def simplified_text(
    text
):

    text = normalize_text(
        text
    )

    # Keep Unicode letters/numbers
    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
        flags=re.UNICODE
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# TITLE MATCHING
# ============================================================

def title_matches(
    page_text,
    title
):

    if not page_text or not title:

        return False

    page_normal = normalize_text(
        page_text
    )

    title_normal = normalize_text(
        title
    )

    # Exact
    if title_normal in page_normal:

        return True

    page_simple = simplified_text(
        page_text
    )

    title_simple = simplified_text(
        title
    )

    if (
        title_simple
        and
        title_simple in page_simple
    ):

        return True

    # Long title partial match
    words = [
        w
        for w in title_simple.split()
        if len(w) >= 3
    ]

    if len(words) >= 5:

        important = words[:10]

        matched = sum(
            1
            for word in important
            if word in page_simple
        )

        required = max(
            3,
            (len(important) + 1) // 2
        )

        if matched >= required:

            return True

    return False


# ============================================================
# CHECK VALID SEREY POST URL
# ============================================================

def is_real_serey_post_url(
    url,
    expected_author=None
):

    if not url:

        return False

    try:

        parsed = urlparse(
            url
        )

        if parsed.netloc.lower() not in [
            "serey.io",
            "www.serey.io"
        ]:

            return False

        path = parsed.path.rstrip("/")

        if "/blog/post/new" in path:

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

        # authors / username / permlink
        if len(parts) < 3:

            return False

        author = parts[1]

        permlink = parts[2]

        if expected_author:

            expected_author = (
                expected_author
                .replace("@", "")
                .strip()
                .lower()
            )

            if author.lower() != expected_author:

                return False

        if not permlink:

            return False

        return True

    except Exception:

        return False


# ============================================================
# VERIFY A DIRECT POST URL
# ============================================================

def verify_post_url(
    page,
    post_url,
    title
):

    if not is_real_serey_post_url(
        post_url,
        SEREY_LOGIN
    ):

        print(
            f"⚠️ Invalid Serey post URL rejected: "
            f"{post_url}",
            flush=True
        )

        return None

    print(
        f"🔎 Checking candidate post URL: "
        f"{post_url}",
        flush=True
    )

    try:

        page.goto(
            post_url,
            timeout=40000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            5000
        )

        current_url = page.url

        print(
            f"Opened URL: {current_url}",
            flush=True
        )

        # ----------------------------------------------------
        # Redirect protection
        # ----------------------------------------------------

        if not is_real_serey_post_url(
            current_url,
            SEREY_LOGIN
        ):

            print(
                "⚠️ Candidate redirected away "
                "from real post URL.",
                flush=True
            )

            return None

        # ----------------------------------------------------
        # BODY TEXT
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:

            body_text = ""

        if title_matches(
            body_text,
            title
        ):

            print(
                "✅ POST TITLE VERIFIED "
                "ON REAL POST PAGE!",
                flush=True
            )

            print(
                f"🔗 VERIFIED URL: {current_url}",
                flush=True
            )

            return current_url

        # ----------------------------------------------------
        # HTML fallback
        # ----------------------------------------------------

        try:

            html = page.content()

        except Exception:

            html = ""

        if title_matches(
            html,
            title
        ):

            print(
                "✅ POST TITLE VERIFIED "
                "IN PAGE HTML!",
                flush=True
            )

            print(
                f"🔗 VERIFIED URL: {current_url}",
                flush=True
            )

            return current_url

    except Exception as e:

        print(
            f"Direct post verification failed: {e}",
            flush=True
        )

    return None


# ============================================================
# VERIFY CURRENT URL AFTER PUBLISH
# ============================================================

def verify_current_page(
    page,
    post
):

    title = post.get(
        "title",
        ""
    ).strip()

    current_url = page.url

    print(
        "\n🔎 FIRST PRIORITY: VERIFY CURRENT SEREY URL",
        flush=True
    )

    print(
        f"Current URL: {current_url}",
        flush=True
    )

    # This is the most important protection.
    # If Serey redirected to a real post URL,
    # verify that URL directly.

    if not is_real_serey_post_url(
        current_url,
        SEREY_LOGIN
    ):

        print(
            "Current URL is not a real published "
            "Serey post URL.",
            flush=True
        )

        return None

    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

        if title_matches(
            body_text,
            title
        ):

            print(
                "🎉 TITLE FOUND ON CURRENT "
                "SEREY POST PAGE!",
                flush=True
            )

            print(
                f"🔗 Current verified URL: "
                f"{current_url}",
                flush=True
            )

            return current_url

    except Exception as e:

        print(
            f"Current page text verification failed: {e}",
            flush=True
        )

    # If text wasn't loaded yet, use direct verification
    return verify_post_url(
        page,
        current_url,
        title
    )


# ============================================================
# FIND POST LINK ON AUTHOR PAGE
# ============================================================

def find_serey_post_on_author_page(
    page,
    title
):

    author = (
        SEREY_LOGIN
        .replace("@", "")
        .strip()
    )

    author_urls = [

        f"{SEREY_BASE}/authors/{author}",

        f"{SEREY_BASE}/authors/@{author}"

    ]

    for author_url in author_urls:

        print(
            f"Checking author page: "
            f"{author_url}",
            flush=True
        )

        try:

            page.goto(
                author_url,
                timeout=40000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(
                6000
            )

            # ------------------------------------------------
            # Search links
            # ------------------------------------------------

            links = page.locator(
                "a"
            )

            count = links.count()

            print(
                f"Author page links found: {count}",
                flush=True
            )

            for i in range(
                count
            ):

                try:

                    link = links.nth(
                        i
                    )

                    href = link.get_attribute(
                        "href"
                    )

                    if not href:

                        continue

                    href = urljoin(
                        SEREY_BASE,
                        href
                    )

                    # ------------------------------------------------
                    # Must be real author post URL
                    # ------------------------------------------------

                    if not is_real_serey_post_url(
                        href,
                        author
                    ):

                        continue

                    # ------------------------------------------------
                    # Link text
                    # ------------------------------------------------

                    try:

                        text = link.inner_text(
                            timeout=1500
                        ).strip()

                    except Exception:

                        text = ""

                    # ------------------------------------------------
                    # Check title in link
                    # ------------------------------------------------

                    if title_matches(
                        text,
                        title
                    ):

                        print(
                            "✅ Matching real post "
                            "link found!",
                            flush=True
                        )

                        print(
                            f"Candidate: {href}",
                            flush=True
                        )

                        return href

                    # Sometimes title is in nearby HTML
                    try:

                        outer_html = link.evaluate(
                            "(el) => el.outerHTML"
                        )

                    except Exception:

                        outer_html = ""

                    if title_matches(
                        outer_html,
                        title
                    ):

                        print(
                            "✅ Matching post found "
                            "from link HTML!",
                            flush=True
                        )

                        return href

                except Exception:

                    continue

        except Exception as e:

            print(
                f"Author page check failed: {e}",
                flush=True
            )

    return None


# ============================================================
# HOMEPAGE SEARCH
# ============================================================

def search_homepage_for_post(
    page,
    title
):

    print(
        "\n🔎 Searching Serey homepage...",
        flush=True
    )

    try:

        page.goto(
            SEREY_BASE,
            timeout=40000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            6000
        )

        links = page.locator(
            "a"
        )

        count = links.count()

        print(
            f"Homepage links found: {count}",
            flush=True
        )

        for i in range(
            min(count, 700)
        ):

            try:

                link = links.nth(
                    i
                )

                href = link.get_attribute(
                    "href"
                )

                if not href:

                    continue

                href = urljoin(
                    SEREY_BASE,
                    href
                )

                if not is_real_serey_post_url(
                    href,
                    SEREY_LOGIN
                ):

                    continue

                try:

                    text = link.inner_text(
                        timeout=1200
                    ).strip()

                except Exception:

                    text = ""

                if title_matches(
                    text,
                    title
                ):

                    print(
                        "✅ Matching post found "
                        "on homepage!",
                        flush=True
                    )

                    return href

            except Exception:

                continue

    except Exception as e:

        print(
            f"Homepage search failed: {e}",
            flush=True
        )

    return None


# ============================================================
# FULL SEREY VERIFICATION
# ============================================================

def verify_serey_post(
    page,
    post,
    current_publish_url=None
):

    title = post.get(
        "title",
        ""
    ).strip()

    print(
        "\n" + "=" * 60,
        flush=True
    )

    print(
        "🔎 VERIFYING SEREY PUBLICATION",
        flush=True
    )

    print(
        f"Expected title: {title}",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    # ========================================================
    # ATTEMPTS
    # ========================================================

    for attempt in range(
        1,
        VERIFY_ATTEMPTS + 1
    ):

        print(
            f"\nVerification attempt "
            f"{attempt}/{VERIFY_ATTEMPTS}",
            flush=True
        )

        # ====================================================
        # 1. MOST IMPORTANT:
        #    URL captured immediately after Publish
        # ====================================================

        if current_publish_url:

            print(
                "1️⃣ Checking URL captured "
                "after final Publish...",
                flush=True
            )

            verified = verify_post_url(
                page,
                current_publish_url,
                title
            )

            if verified:

                print(
                    "🎉 VERIFIED USING "
                    "PUBLISH REDIRECT URL!",
                    flush=True
                )

                return verified

        # ====================================================
        # 2. CURRENT PAGE
        # ====================================================

        print(
            "2️⃣ Checking current browser page...",
            flush=True
        )

        current_url = page.url

        if is_real_serey_post_url(
            current_url,
            SEREY_LOGIN
        ):

            verified = verify_current_page(
                page,
                post
            )

            if verified:

                return verified

        # ====================================================
        # 3. AUTHOR PAGE
        # ====================================================

        print(
            "3️⃣ Checking Serey author page...",
            flush=True
        )

        author_post = (
            find_serey_post_on_author_page(
                page,
                title
            )
        )

        if author_post:

            verified = verify_post_url(
                page,
                author_post,
                title
            )

            if verified:

                print(
                    "🎉 VERIFIED FROM "
                    "AUTHOR PAGE!",
                    flush=True
                )

                return verified

        # ====================================================
        # 4. HOMEPAGE
        # ====================================================

        print(
            "4️⃣ Checking Serey homepage...",
            flush=True
        )

        home_post = (
            search_homepage_for_post(
                page,
                title
            )
        )

        if home_post:

            verified = verify_post_url(
                page,
                home_post,
                title
            )

            if verified:

                print(
                    "🎉 VERIFIED FROM "
                    "HOMEPAGE!",
                    flush=True
                )

                return verified

        # ====================================================
        # WAIT
        # ====================================================

        if attempt < VERIFY_ATTEMPTS:

            print(
                f"⏳ Serey may still be "
                f"propagating the post.",
                flush=True
            )

            print(
                f"Waiting "
                f"{VERIFY_WAIT_SECONDS} seconds...",
                flush=True
            )

            time.sleep(
                VERIFY_WAIT_SECONDS
            )

    print(
        "\n❌ REAL SEREY POST URL "
        "COULD NOT BE VERIFIED.",
        flush=True
    )

    return None


# ============================================================
# CATEGORY SELECTION
# ============================================================

def select_category(
    page
):

    print(
        "\n  - Selecting category...",
        flush=True
    )

    possible_categories = [
        "general",
        "blog",
        "lifestyle",
        "culture",
        "technology",
        "tech",
        "news",
        "other"
    ]

    try:

        selectors = [
            'div:has-text("Select category")',
            '.ant-select',
            'input[placeholder*="category" i]',
            '[role="combobox"]'
        ]

        dropdown = None

        for selector in selectors:

            try:

                loc = page.locator(
                    selector
                )

                if loc.count() > 0:

                    for i in range(
                        min(loc.count(), 10)
                    ):

                        candidate = loc.nth(i)

                        try:

                            if candidate.is_visible():

                                dropdown = candidate

                                break

                        except Exception:

                            continue

                if dropdown:

                    break

            except Exception:

                continue

        if dropdown:

            dropdown.click(
                force=True
            )

            page.wait_for_timeout(
                1500
            )

            options = page.locator(
                '[role="option"], '
                '.ant-select-item-option, '
                'li'
            )

            option_count = (
                options.count()
            )

            for i in range(
                option_count
            ):

                try:

                    option = options.nth(
                        i
                    )

                    text = option.inner_text(
                        timeout=1000
                    ).strip()

                    if text.lower() in (
                        possible_categories
                    ):

                        option.click(
                            force=True
                        )

                        print(
                            f"  - Category selected: "
                            f"{text}",
                            flush=True
                        )

                        return True

                except Exception:

                    continue

            # Keyboard fallback
            page.keyboard.press(
                "ArrowDown"
            )

            page.keyboard.press(
                "Enter"
            )

            print(
                "  - Category selected "
                "via keyboard fallback.",
                flush=True
            )

            return True

        # Last fallback
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
            "via final keyboard fallback.",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"  ⚠️ Category selection skipped: {e}",
            flush=True
        )

        # Category should NOT stop publishing
        return False


# ============================================================
# FIND PUBLISH BUTTON
# ============================================================

def get_publish_buttons(
    page
):

    selectors = [

        '.ant-modal-content button:has-text("Publish")',

        '.ant-modal-footer button:has-text("Publish")',

        'button:has-text("Publish")'

    ]

    for selector in selectors:

        try:

            buttons = page.locator(
                selector
            )

            if buttons.count() > 0:

                return buttons

        except Exception:

            continue

    return None


# ============================================================
# PUBLISH TO SEREY
# ============================================================

def publish_to_serey(
    page,
    post
):

    title = post.get(
        "title",
        ""
    ).strip()

    print(
        "\n" + "-" * 60,
        flush=True
    )

    print(
        f"---> Publishing to Serey: {title}",
        flush=True
    )

    temp_img_path = TEMP_IMG_FILE

    publish_url = None

    try:

        # ====================================================
        # 1. OPEN NEW POST
        # ====================================================

        print(
            "\nOpening Serey editor...",
            flush=True
        )

        page.goto(
            f"{SEREY_BASE}/blog/post/new",
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            5000
        )

        # ====================================================
        # 2. TITLE
        # ====================================================

        title_box = page.locator(
            'input[placeholder*="title" i], '
            'input[placeholder*="Title"]'
        ).first

        title_box.wait_for(
            state="visible",
            timeout=20000
        )

        title_box.fill(
            title
        )

        print(
            "  - Title filled!",
            flush=True
        )

        # ====================================================
        # 3. BODY
        # ====================================================

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
            post.get(
                "body",
                ""
            )
        )

        print(
            "  - Clean body content filled!",
            flush=True
        )

        page.wait_for_timeout(
            2000
        )

        # ====================================================
        # 4. IMAGE
        # ====================================================

        thumbnail = prepare_thumbnail(
            post
        )

        if thumbnail:

            try:

                file_inputs = page.locator(
                    'input[type="file"]'
                )

                file_count = (
                    file_inputs.count()
                )

                if file_count > 0:

                    file_inputs.first.set_input_files(
                        thumbnail["path"]
                    )

                    print(
                        "  - Thumbnail uploaded!",
                        flush=True
                    )

                    print(
                        f"  - Source: "
                        f"{thumbnail['source']}",
                        flush=True
                    )

                    if thumbnail.get(
                        "photographer"
                    ):

                        print(
                            f"  - Photographer: "
                            f"{thumbnail['photographer']}",
                            flush=True
                        )

                    page.wait_for_timeout(
                        5000
                    )

                else:

                    print(
                        "  ⚠️ File input not found.",
                        flush=True
                    )

            except Exception as e:

                print(
                    f"  ⚠️ Image upload failed: {e}",
                    flush=True
                )

        else:

            print(
                "  ⚠️ No thumbnail available.",
                flush=True
            )

            print(
                "  - Continuing without image.",
                flush=True
            )

        # ====================================================
        # 5. FIRST PUBLISH
        # ====================================================

        print(
            "\n  - Looking for first Publish button...",
            flush=True
        )

        publish_buttons = get_publish_buttons(
            page
        )

        if not publish_buttons:

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

        page.wait_for_timeout(
            7000
        )

        # ====================================================
        # 6. CATEGORY
        # ====================================================

        select_category(
            page
        )

        page.wait_for_timeout(
            2500
        )

        # ====================================================
        # 7. FINAL PUBLISH
        # ====================================================

        print(
            "\n  - Looking for FINAL Publish button...",
            flush=True
        )

        final_buttons = get_publish_buttons(
            page
        )

        if not final_buttons:

            raise RuntimeError(
                "Final Publish button not found."
            )

        count = final_buttons.count()

        print(
            f"  - Found {count} Publish "
            f"button(s).",
            flush=True
        )

        # LAST button is normally modal confirmation
        final_buttons.last.click(
            force=True
        )

        print(
            "  - FINAL Publish button clicked!",
            flush=True
        )

        # ====================================================
        # 8. VERY IMPORTANT:
        #    CAPTURE URL AFTER PUBLISH
        # ====================================================

        print(
            "\n  ⏳ Waiting for Serey redirect...",
            flush=True
        )

        # Small initial wait
        page.wait_for_timeout(
            3000
        )

        publish_url = page.url

        print(
            f"  🌐 URL immediately after "
            f"Publish: {publish_url}",
            flush=True
        )

        # Give Serey additional time
        page.wait_for_timeout(
            7000
        )

        # Update URL if browser changed it
        if page.url != publish_url:

            publish_url = page.url

            print(
                f"  🌐 Updated Serey URL: "
                f"{publish_url}",
                flush=True
            )

        # ====================================================
        # 9. REAL VERIFICATION
        # ====================================================

        verified_url = (
            verify_serey_post(
                page,
                post,
                current_publish_url=publish_url
            )
        )

        # ====================================================
        # 10. DELETE TEMP IMAGE
        # ====================================================

        if os.path.exists(
            temp_img_path
        ):

            try:

                os.remove(
                    temp_img_path
                )

            except Exception:

                pass

        # ====================================================
        # 11. SUCCESS ONLY IF VERIFIED
        # ====================================================

        if verified_url:

            print(
                "\n" + "=" * 60,
                flush=True
            )

            print(
                "🎉 VERIFIED & CONFIRMED!",
                flush=True
            )

            print(
                f"Title: {title}",
                flush=True
            )

            print(
                f"Serey URL: {verified_url}",
                flush=True
            )

            print(
                "=" * 60,
                flush=True
            )

            return {

                "success":
                    True,

                "url":
                    verified_url

            }

        print(
            "\n❌ PUBLISH COULD NOT BE VERIFIED.",
            flush=True
        )

        print(
            "The post will NOT be added to "
            "synced_posts.json.",
            flush=True
        )

        return {

            "success":
                False,

            "url":
                None

        }

    except Exception as e:

        print(
            f"\n❌ Failed to publish post "
            f"on Serey: {e}",
            flush=True
        )

        return {

            "success":
                False,

            "url":
                None

        }

    finally:

        if os.path.exists(
            temp_img_path
        ):

            try:

                os.remove(
                    temp_img_path
                )

            except Exception:

                pass


# ============================================================
# LOGIN TO SEREY
# ============================================================

def login_to_serey(
    page
):

    print(
        "\nLogging into Serey.io...",
        flush=True
    )

    try:

        page.goto(
            SEREY_BASE,
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            5000
        )

        # ----------------------------------------------------
        # If already logged in
        # ----------------------------------------------------

        current_url = page.url

        if (
            "/blog/post/new"
            in current_url
        ):

            print(
                "Already logged in.",
                flush=True
            )

            return True

        # ----------------------------------------------------
        # Login button
        # ----------------------------------------------------

        print(
            "Clicking Log in button...",
            flush=True
        )

        login_buttons = page.locator(
            'a:has-text("Log in"), '
            'button:has-text("Log in"), '
            'a:has-text("Log In"), '
            'button:has-text("Log In")'
        )

        if login_buttons.count() == 0:

            # Maybe already logged in
            body_text = ""

            try:

                body_text = page.locator(
                    "body"
                ).inner_text(
                    timeout=5000
                )

            except Exception:

                pass

            if (
                "log out"
                in body_text.lower()
                or
                "logout"
                in body_text.lower()
            ):

                print(
                    "✅ Already logged into Serey.",
                    flush=True
                )

                return True

            raise RuntimeError(
                "Log in button not found."
            )

        login_buttons.first.click(
            force=True
        )

        page.wait_for_timeout(
            5000
        )

        # ----------------------------------------------------
        # Username
        # ----------------------------------------------------

        username_box = page.locator(
            'input[placeholder="Username"], '
            'input[placeholder*="Username" i]'
        ).first

        username_box.wait_for(
            state="visible",
            timeout=20000
        )

        username_box.fill(
            SEREY_LOGIN
        )

        # ----------------------------------------------------
        # Password / Private Key
        # ----------------------------------------------------

        password_box = page.locator(
            'input[placeholder="Private Key or Password"], '
            'input[placeholder*="Private Key" i], '
            'input[type="password"]'
        ).first

        password_box.wait_for(
            state="visible",
            timeout=20000
        )

        password_box.fill(
            SEREY_PASSWORD
        )

        # ----------------------------------------------------
        # Login submit
        # ----------------------------------------------------

        submit_buttons = page.locator(
            '.ant-modal-content button:has-text("Log in"), '
            '.ant-modal-content button:has-text("Log In"), '
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        )

        if submit_buttons.count() == 0:

            raise RuntimeError(
                "Login submit button not found."
            )

        submit_buttons.last.click(
            force=True
        )

        print(
            "Login button submitted.",
            flush=True
        )

        page.wait_for_timeout(
            8000
        )

        # ----------------------------------------------------
        # Check errors
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:

            body_text = ""

        lower = body_text.lower()

        error_phrases = [

            "invalid password",
            "invalid private key",
            "login failed",
            "incorrect password",
            "authentication failed",
            "invalid credentials"

        ]

        for phrase in error_phrases:

            if phrase in lower:

                raise RuntimeError(
                    f"Serey login error: {phrase}"
                )

        # ----------------------------------------------------
        # Check logged-in state
        # ----------------------------------------------------

        if (
            "log in"
            not in lower
            or
            "log out"
            in lower
            or
            "logout"
            in lower
        ):

            print(
                "✅ LOGGED INTO SEREY SUCCESSFULLY!",
                flush=True
            )

            print(
                f"Current URL: {page.url}",
                flush=True
            )

            return True

        # Even if text check is inconclusive,
        # try opening editor.
        print(
            "Login text check inconclusive. "
            "Testing editor access...",
            flush=True
        )

        page.goto(
            f"{SEREY_BASE}/blog/post/new",
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            4000
        )

        if (
            "/blog/post/new"
            in page.url
        ):

            print(
                "✅ Serey editor accessible. "
                "Login successful.",
                flush=True
            )

            return True

        raise RuntimeError(
            "Could not confirm Serey login."
        )

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

    print(
        f"Steemit username: @{STEEM_USERNAME}",
        flush=True
    )

    print(
        f"Serey login: {SEREY_LOGIN}",
        flush=True
    )

    print(
        f"Posts per run: {POSTS_PER_RUN}",
        flush=True
    )

    print(
        f"Maximum historical posts: {MAX_POSTS}",
        flush=True
    )

    if PEXELS_API_KEY:

        print(
            "Pexels API key: AVAILABLE",
            flush=True
        )

    else:

        print(
            "Pexels API key: NOT AVAILABLE "
            "(Pexels fallback disabled)",
            flush=True
        )

    # ========================================================
    # LOAD SYNCED
    # ========================================================

    synced_posts = (
        load_synced_posts()
    )

    print(
        f"\nPreviously synced posts: "
        f"{len(synced_posts)}",
        flush=True
    )

    # ========================================================
    # FETCH
    # ========================================================

    posts = get_recent_posts()

    print(
        f"Total posts fetched: "
        f"{len(posts)}",
        flush=True
    )

    if not posts:

        print(
            "No Steemit posts found.",
            flush=True
        )

        return

    # ========================================================
    # FIND UNSYNCED
    # ========================================================

    new_posts = []

    for post in posts:

        post_id = (
            f'{post["author"]}/'
            f'{post["permlink"]}'
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

    # ========================================================
    # POSTS FOR THIS RUN
    # ========================================================

    new_posts_to_run = (
        new_posts[
            :POSTS_PER_RUN
        ]
    )

    print(
        f"Publishing this run: "
        f"{len(new_posts_to_run)} post(s)",
        flush=True
    )

    if not new_posts_to_run:

        print(
            "No new posts to sync!",
            flush=True
        )

        return

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    with sync_playwright() as p:

        browser = None

        try:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ]
            )

            context = browser.new_context(

                viewport={
                    "width": 1280,
                    "height": 800
                },

                user_agent=BROWSER_USER_AGENT,

                locale="en-US"

            )

            page = context.new_page()

            # =================================================
            # LOGIN
            # =================================================

            if not login_to_serey(
                page
            ):

                print(
                    "❌ Cannot continue without Serey login.",
                    flush=True
                )

                return

            # =================================================
            # PUBLISH
            # =================================================

            for post in new_posts_to_run:

                post_id = (
                    f'{post["author"]}/'
                    f'{post["permlink"]}'
                )

                print(
                    "\n" + "#" * 60,
                    flush=True
                )

                print(
                    f"Processing: {post_id}",
                    flush=True
                )

                print(
                    f"Title: {post['title']}",
                    flush=True
                )

                print(
                    "#" * 60,
                    flush=True
                )

                result = publish_to_serey(
                    page,
                    post
                )

                # =============================================
                # SAVE ONLY AFTER REAL VERIFICATION
                # =============================================

                if (
                    result
                    and
                    result.get("success")
                ):

                    synced_posts.add(
                        post_id
                    )

                    saved = save_synced_posts(
                        synced_posts
                    )

                    if saved:

                        print(
                            "\n✅ SUCCESSFULLY SAVED "
                            "AS SYNCED!",
                            flush=True
                        )

                    else:

                        print(
                            "\n⚠️ Post verified but "
                            "synced_posts.json could not "
                            "be saved.",
                            flush=True
                        )

                    if result.get(
                        "url"
                    ):

                        print(
                            f"🔗 Published Serey URL: "
                            f"{result['url']}",
                            flush=True
                        )

                else:

                    print(
                        "\n⚠️ POST WAS NOT VERIFIED.",
                        flush=True
                    )

                    print(
                        "❌ It will NOT be added "
                        "to synced_posts.json.",
                        flush=True
                    )

                    print(
                        "It can be retried on "
                        "the next GitHub Actions run.",
                        flush=True
                    )

        finally:

            if browser:

                try:

                    browser.close()

                except Exception:

                    pass

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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
