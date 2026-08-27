import os
import json
import requests
import time
import re
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

# নিরাপত্তার জন্য সর্বোচ্চ historical posts
MAX_POSTS = 6000

# সর্বোচ্চ Steem batches
MAX_BATCHES = 70


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
# SEREY
# ============================================================

SEREY_BASE = "https://serey.io"


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
                f"Steem RPC failed: {e}",
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

    except Exception as e:

        print(
            f"Could not save synced_posts.json: {e}",
            flush=True
        )


# ============================================================
# IMAGE URL HELPERS
# ============================================================

def clean_url(url):

    if not url:

        return None

    url = url.strip()

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
        "i.imgur.com"

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


def extract_all_images(
    body,
    metadata
):

    images = []

    # --------------------------------------------------------
    # Metadata
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

                    if isinstance(
                        img,
                        str
                    ):

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
    # Raw URLs
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

    images = extract_all_images(
        body_text,
        json_metadata_str
    )

    first_image = (
        images[0]
        if images
        else None
    )

    clean_body = body_text or ""

    # Remove Markdown image syntax
    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )

    body_images = extract_all_images(
        body_text,
        "{}"
    )

    for url in body_images:

        clean_body = clean_body.replace(
            url,
            ""
        )

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
# FETCH STEEM POSTS
# ============================================================

def get_recent_posts():

    print(
        f"\nFetching ALL historical posts from "
        f"Steemit: @{STEEM_USERNAME}",
        flush=True
    )

    all_posts = []

    seen_permlinks = set()

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

            params[
                "start_author"
            ] = start_author

            params[
                "start_permlink"
            ] = start_permlink

        try:

            result = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                params
            )

        except Exception as e:

            print(
                f"Failed to fetch Steemit batch "
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

        print(
            f"Batch #{batch_number}: "
            f"{len(result)} received, "
            f"{len(batch)} new posts.",
            flush=True
        )

        if not batch:

            break

        for post in batch:

            if (
                post.get("author")
                != STEEM_USERNAME
            ):

                continue

            permlink = post.get(
                "permlink"
            )

            if not permlink:

                continue

            if permlink in seen_permlinks:

                continue

            seen_permlinks.add(
                permlink
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

                "author": post.get(
                    "author"
                ),

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

        print(
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
                "Stopping.",
                flush=True
            )

            break

        start_author = (
            new_start_author
        )

        start_permlink = (
            new_start_permlink
        )

        if len(result) < 100:

            print(
                "Last Steemit batch contains "
                "fewer than 100 posts.",
                flush=True
            )

            break

        if len(all_posts) >= MAX_POSTS:

            print(
                f"Reached {MAX_POSTS}-post safety limit.",
                flush=True
            )

            break

        time.sleep(
            0.3
        )

    # Oldest -> newest
    all_posts.reverse()

    print(
        f"Total historical posts fetched: "
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

    headers = {

        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/122.0.0.0 "
            "Safari/537.36",

        "Accept":
            "image/avif,image/webp,image/apng,"
            "image/*,*/*;q=0.8"

    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=20,
            allow_redirects=True
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type",
            ""
        ).lower()

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

    if post.get(
        "image"
    ):

        candidates.append(
            post["image"]
        )

    for img in post.get(
        "image_candidates",
        []
    ):

        if img not in candidates:

            candidates.append(
                img
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
                f"Image attempt {attempt}...",
                flush=True
            )

            if download_image(
                url,
                output_path
            ):

                print(
                    "✅ Steemit image "
                    "downloaded successfully.",
                    flush=True
                )

                return url

            time.sleep(
                1
            )

    print(
        "❌ No working Steemit image found.",
        flush=True
    )

    return None


# ============================================================
# PEXELS QUERY
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

    queries.extend([
        "news",
        "people",
        "world",
        "technology"
    ])

    result = []

    for q in queries:

        q = q.strip()

        if (
            q
            and
            q.lower()
            not in [
                x.lower()
                for x in result
            ]
        ):

            result.append(
                q
            )

    return result


# ============================================================
# PEXELS FALLBACK
# ============================================================

def get_pexels_image(
    post,
    output_path
):

    print(
        "🔄 Trying Pexels fallback...",
        flush=True
    )

    if not PEXELS_API_KEY:

        print(
            "❌ PEXELS_API_KEY not found.",
            flush=True
        )

        return None

    queries = build_pexels_queries(
        post
    )

    headers = {
        "Authorization":
            PEXELS_API_KEY
    }

    endpoint = (
        "https://api.pexels.com/v1/search"
    )

    for query in queries:

        print(
            f"🔎 Pexels search query: {query}",
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
                    f"{response.status_code} "
                    f"{response.text[:300]}",
                    flush=True
                )

                continue

            data = response.json()

            photos = data.get(
                "photos",
                []
            )

            if not photos:

                print(
                    "No Pexels photos found.",
                    flush=True
                )

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
                        f"   Photographer: "
                        f"{photographer}",
                        flush=True
                    )

                    print(
                        f"   Photo page: "
                        f"{photo_page}",
                        flush=True
                    )

                    return {

                        "source": "Pexels",

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

        time.sleep(
            1
        )

    print(
        "❌ No working Pexels image found.",
        flush=True
    )

    return None


# ============================================================
# PREPARE THUMBNAIL
# ============================================================

def prepare_thumbnail(
    post
):

    temp_path = (
        "temp_thumbnail.jpg"
    )

    if os.path.exists(
        temp_path
    ):

        try:

            os.remove(
                temp_path
            )

        except Exception:

            pass

    # --------------------------------------------------------
    # FIRST: STEEMIT
    # --------------------------------------------------------

    print(
        "Searching for working "
        "Steemit image...",
        flush=True
    )

    steemit_image = (
        find_working_steemit_image(
            post,
            temp_path
        )
    )

    if steemit_image:

        return {

            "path":
                temp_path,

            "source":
                "Steemit",

            "url":
                steemit_image,

            "photographer":
                "",

            "photo_page":
                ""

        }

    print(
        "⚠️ Steemit image unavailable.",
        flush=True
    )

    # --------------------------------------------------------
    # SECOND: PEXELS
    # --------------------------------------------------------

    pexels_result = get_pexels_image(
        post,
        temp_path
    )

    if pexels_result:

        return {

            "path":
                temp_path,

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

    print(
        "⚠️ No thumbnail available.",
        flush=True
    )

    return None


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(
    text
):

    if not text:

        return ""

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# TITLE MATCH
# ============================================================

def title_matches(
    page_text,
    title
):

    page_text = normalize_text(
        page_text
    )

    title = normalize_text(
        title
    )

    if (
        not page_text
        or
        not title
    ):

        return False

    # --------------------------------------------------------
    # Exact match
    # --------------------------------------------------------

    if title in page_text:

        return True

    # --------------------------------------------------------
    # Punctuation removed
    # --------------------------------------------------------

    simple_title = re.sub(
        r"[^\w\s]",
        "",
        title,
        flags=re.UNICODE
    )

    simple_page = re.sub(
        r"[^\w\s]",
        "",
        page_text,
        flags=re.UNICODE
    )

    if (
        simple_title
        and
        simple_title in simple_page
    ):

        return True

    # --------------------------------------------------------
    # Long title partial verification
    # --------------------------------------------------------

    words = simple_title.split()

    if len(words) >= 5:

        important_words = [
            w
            for w in words
            if len(w) >= 3
        ][:8]

        matches = sum(
            1
            for word in important_words
            if word in simple_page
        )

        if matches >= max(
            3,
            len(important_words) // 2
        ):

            return True

    return False


# ============================================================
# FIND POST LINK ON AUTHOR PAGE
# ============================================================

def find_serey_post_on_author_page(
    page,
    title,
    author
):

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
                timeout=30000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(
                5000
            )

            # ------------------------------------------------
            # Page text
            # ------------------------------------------------

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
                        "✅ TITLE FOUND ON "
                        "AUTHOR PAGE!",
                        flush=True
                    )

            except Exception:

                pass

            # ------------------------------------------------
            # Search all links
            # ------------------------------------------------

            links = page.locator(
                "a"
            )

            count = links.count()

            print(
                f"Found {count} links "
                f"on author page.",
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

                    text = ""

                    try:

                        text = link.inner_text(
                            timeout=1500
                        ).strip()

                    except Exception:

                        pass

                    # ------------------------------------------------
                    # Convert relative URL
                    # ------------------------------------------------

                    if href.startswith(
                        "/"
                    ):

                        href = (
                            SEREY_BASE
                            + href
                        )

                    # ------------------------------------------------
                    # IMPORTANT:
                    # ONLY REAL AUTHOR POST URL
                    # ------------------------------------------------

                    if not href.startswith(
                        f"{SEREY_BASE}/authors/"
                    ):

                        continue

                    # ------------------------------------------------
                    # NEVER ACCEPT EDITOR URL
                    # ------------------------------------------------

                    if "/blog/post/new" in href:

                        continue

                    # ------------------------------------------------
                    # Title match
                    # ------------------------------------------------

                    combined = (
                        f"{text} {href}"
                    )

                    if title_matches(
                        combined,
                        title
                    ):

                        print(
                            "✅ MATCHING REAL "
                            "POST LINK FOUND!",
                            flush=True
                        )

                        print(
                            f"🔗 Candidate URL: "
                            f"{href}",
                            flush=True
                        )

                        return href

                except Exception:

                    continue

        except Exception as e:

            print(
                f"Author page check failed: "
                f"{e}",
                flush=True
            )

    return None


# ============================================================
# SEARCH SEREY HOMEPAGE
# ============================================================

def search_homepage_for_post(
    page,
    title
):

    print(
        "🔎 Searching Serey homepage "
        "for matching post...",
        flush=True
    )

    try:

        page.goto(
            SEREY_BASE,
            timeout=30000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            5000
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
            min(
                count,
                500
            )
        ):

            try:

                link = links.nth(
                    i
                )

                text = link.inner_text(
                    timeout=1000
                ).strip()

                href = link.get_attribute(
                    "href"
                )

                if not href:

                    continue

                if href.startswith(
                    "/"
                ):

                    href = (
                        SEREY_BASE
                        + href
                    )

                # NEVER accept editor URL
                if "/blog/post/new" in href:

                    continue

                # Prefer real author post links
                if not href.startswith(
                    f"{SEREY_BASE}/authors/"
                ):

                    continue

                combined = (
                    f"{text} {href}"
                )

                if title_matches(
                    combined,
                    title
                ):

                    print(
                        "✅ MATCHING POST FOUND "
                        "ON SEREY HOMEPAGE!",
                        flush=True
                    )

                    print(
                        f"🔗 URL: {href}",
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
# VERIFY DIRECT POST PAGE
# ============================================================

def verify_post_url(
    page,
    post_url,
    title
):

    # ========================================================
    # CRITICAL PROTECTION
    # ========================================================

    if not post_url:

        return None

    if "/blog/post/new" in post_url:

        print(
            "⚠️ REFUSING TO VERIFY "
            "/blog/post/new.",
            flush=True
        )

        print(
            "⚠️ This is the Serey editor page, "
            "NOT a published post.",
            flush=True
        )

        return None

    # --------------------------------------------------------
    # Only author URLs accepted
    # --------------------------------------------------------

    if not post_url.startswith(
        f"{SEREY_BASE}/authors/"
    ):

        print(
            f"⚠️ Rejecting non-author URL: "
            f"{post_url}",
            flush=True
        )

        return None

    print(
        f"Checking candidate post URL: "
        f"{post_url}",
        flush=True
    )

    try:

        page.goto(
            post_url,
            timeout=30000,
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
        # Reject editor redirect
        # ----------------------------------------------------

        if "/blog/post/new" in current_url:

            print(
                "⚠️ Serey redirected to "
                "/blog/post/new.",
                flush=True
            )

            return None

        # ----------------------------------------------------
        # URL must remain author URL
        # ----------------------------------------------------

        if not current_url.startswith(
            f"{SEREY_BASE}/authors/"
        ):

            print(
                "⚠️ Current URL is not "
                "a real author post URL.",
                flush=True
            )

            return None

        # ----------------------------------------------------
        # BODY TEXT
        # ----------------------------------------------------

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
                "✅ POST TITLE VERIFIED "
                "ON REAL POST PAGE!",
                flush=True
            )

            print(
                f"✅ VERIFIED URL: "
                f"{current_url}",
                flush=True
            )

            return current_url

        # ----------------------------------------------------
        # FULL HTML
        # ----------------------------------------------------

        html = page.content()

        if title_matches(
            html,
            title
        ):

            print(
                "✅ POST TITLE FOUND "
                "IN PAGE HTML!",
                flush=True
            )

            print(
                f"✅ VERIFIED URL: "
                f"{current_url}",
                flush=True
            )

            return current_url

    except Exception as e:

        print(
            f"Direct post verification "
            f"failed: {e}",
            flush=True
        )

    return None


# ============================================================
# FULL SEREY VERIFICATION
# ============================================================

def verify_serey_post(
    page,
    post,
    max_attempts=8
):

    title = post.get(
        "title",
        ""
    ).strip()

    author = SEREY_LOGIN

    print(
        "\n🔎 VERIFYING POST ON SEREY...",
        flush=True
    )

    print(
        f"Expected title: {title}",
        flush=True
    )

    # ========================================================
    # DO NOT CHECK CURRENT EDITOR PAGE
    # ========================================================

    for attempt in range(
        1,
        max_attempts + 1
    ):

        print(
            f"Verification attempt "
            f"{attempt}/{max_attempts}",
            flush=True
        )

        # ----------------------------------------------------
        # 1. AUTHOR PAGE
        # ----------------------------------------------------

        post_url = (
            find_serey_post_on_author_page(
                page,
                title,
                author
            )
        )

        if post_url:

            verified = verify_post_url(
                page,
                post_url,
                title
            )

            if verified:

                print(
                    "✅ REAL SEREY POST URL VERIFIED!",
                    flush=True
                )

                return verified

        # ----------------------------------------------------
        # 2. HOMEPAGE
        # ----------------------------------------------------

        homepage_post = (
            search_homepage_for_post(
                page,
                title
            )
        )

        if homepage_post:

            verified = verify_post_url(
                page,
                homepage_post,
                title
            )

            if verified:

                return verified

        # ----------------------------------------------------
        # 3. DIRECT AUTHOR PAGE REFRESH
        # ----------------------------------------------------

        try:

            author_url = (
                f"{SEREY_BASE}/authors/{author}"
            )

            print(
                f"Refreshing author page: "
                f"{author_url}",
                flush=True
            )

            page.goto(
                author_url,
                timeout=30000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(
                5000
            )

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
                    "✅ TITLE FOUND ON "
                    "AUTHOR PAGE.",
                    flush=True
                )

                found_url = (
                    find_serey_post_on_author_page(
                        page,
                        title,
                        author
                    )
                )

                if found_url:

                    verified = verify_post_url(
                        page,
                        found_url,
                        title
                    )

                    if verified:

                        return verified

        except Exception as e:

            print(
                f"Author refresh failed: {e}",
                flush=True
            )

        # ----------------------------------------------------
        # WAIT
        # ----------------------------------------------------

        if attempt < max_attempts:

            print(
                "⏳ Post may still be propagating.",
                flush=True
            )

            print(
                "Waiting 10 seconds...",
                flush=True
            )

            time.sleep(
                10
            )

    print(
        "❌ REAL SEREY POST URL "
        "COULD NOT BE VERIFIED.",
        flush=True
    )

    return None


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

    temp_img_path = (
        "temp_thumbnail.jpg"
    )

    try:

        # ----------------------------------------------------
        # 1. NEW POST
        # ----------------------------------------------------

        page.goto(
            f"{SEREY_BASE}/blog/post/new",
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(
            4000
        )

        # ----------------------------------------------------
        # 2. TITLE
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
        # 3. BODY
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

        page.wait_for_timeout(
            2000
        )

        # ----------------------------------------------------
        # 4. THUMBNAIL
        # ----------------------------------------------------

        thumbnail = prepare_thumbnail(
            post
        )

        if thumbnail:

            try:

                file_inputs = page.locator(
                    'input[type="file"]'
                )

                count = file_inputs.count()

                if count > 0:

                    file_inputs.first.set_input_files(
                        thumbnail["path"]
                    )

                    print(
                        "  - Thumbnail image uploaded!",
                        flush=True
                    )

                    print(
                        f"  - Image source: "
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
                        "⚠️ No file input found.",
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
        # 5. FIRST PUBLISH
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

        page.wait_for_timeout(
            7000
        )

        # ----------------------------------------------------
        # 6. CATEGORY
        # ----------------------------------------------------

        try:

            dropdowns = page.locator(
                'div:has-text("Select category"), '
                '.ant-select, '
                'input[placeholder*="category" i]'
            )

            if dropdowns.count() > 0:

                dropdowns.last.click(
                    force=True
                )

                page.wait_for_timeout(
                    1500
                )

                options = page.locator(
                    '.ant-select-item-option, '
                    '[role="option"], '
                    'li'
                )

                option_count = (
                    options.count()
                )

                category_selected = False

                for i in range(
                    option_count
                ):

                    try:

                        text = options.nth(
                            i
                        ).inner_text(
                            timeout=1000
                        )

                        if text.strip().lower() in [

                            "general",
                            "culture",
                            "blog",
                            "lifestyle",
                            "technology",
                            "tech"

                        ]:

                            options.nth(
                                i
                            ).click(
                                force=True
                            )

                            category_selected = True

                            print(
                                f"  - Category selected: "
                                f"{text.strip()}",
                                flush=True
                            )

                            break

                    except Exception:

                        continue

                if not category_selected:

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

            else:

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

        except Exception as e:

            print(
                f"  - Category selection "
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

            except Exception:

                pass

        page.wait_for_timeout(
            2500
        )

        # ----------------------------------------------------
        # 7. FINAL PUBLISH
        # ----------------------------------------------------

        modal_buttons = page.locator(
            '.ant-modal-content button:has-text("Publish"), '
            '.ant-modal-footer button:has-text("Publish"), '
            'button:has-text("Publish")'
        )

        count = modal_buttons.count()

        if count == 0:

            raise RuntimeError(
                "Final Publish button not found."
            )

        print(
            f"  - Found {count} Publish "
            f"button(s) for final step.",
            flush=True
        )

        modal_buttons.last.click(
            force=True
        )

        print(
            "  - Final Publish button clicked!",
            flush=True
        )

        # ----------------------------------------------------
        # 8. WAIT
        # ----------------------------------------------------

        print(
            "  - Waiting for Serey "
            "publish result...",
            flush=True
        )

        page.wait_for_timeout(
            5000
        )

        # ----------------------------------------------------
        # 9. VERIFY
        # ----------------------------------------------------

        verified_url = (
            verify_serey_post(
                page,
                post,
                max_attempts=8
            )
        )

        # ----------------------------------------------------
        # CLEAN TEMP IMAGE
        # ----------------------------------------------------

        if os.path.exists(
            temp_img_path
        ):

            try:

                os.remove(
                    temp_img_path
                )

            except Exception:

                pass

        # ----------------------------------------------------
        # SUCCESS ONLY AFTER REAL VERIFICATION
        # ----------------------------------------------------

        if verified_url:

            print(
                "✅ SEREY POST VERIFIED!",
                flush=True
            )

            print(
                f"🔗 Serey URL: "
                f"{verified_url}",
                flush=True
            )

            return {

                "success":
                    True,

                "url":
                    verified_url

            }

        print(
            "⚠️ Verification failed. "
            "Post will NOT be saved as synced.",
            flush=True
        )

        return {

            "success":
                False,

            "url":
                None

        }

    except Exception as e:

        if os.path.exists(
            temp_img_path
        ):

            try:

                os.remove(
                    temp_img_path
                )

            except Exception:

                pass

        print(
            f"❌ Failed to publish post "
            f"on Serey: {e}",
            flush=True
        )

        return {

            "success":
                False,

            "url":
                None

        }


# ============================================================
# SEREY LOGIN
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
            4000
        )

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
        # USERNAME
        # ----------------------------------------------------

        username_box = page.locator(
            'input[placeholder="Username"], '
            'input[placeholder*="Username"]'
        ).first

        username_box.wait_for(
            state="visible",
            timeout=20000
        )

        username_box.fill(
            SEREY_LOGIN
        )

        # ----------------------------------------------------
        # PASSWORD / PRIVATE KEY
        # ----------------------------------------------------

        password_box = page.locator(
            'input[placeholder="Private Key or Password"], '
            'input[placeholder*="Private Key"], '
            'input[type="password"]'
        ).first

        password_box.fill(
            SEREY_PASSWORD
        )

        # ----------------------------------------------------
        # LOGIN SUBMIT
        # ----------------------------------------------------

        login_submit = page.locator(
            '.ant-modal-content button:has-text("Log in"), '
            '.ant-modal-content button:has-text("Log In"), '
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        )

        if login_submit.count() == 0:

            raise RuntimeError(
                "Login submit button not found."
            )

        login_submit.last.click(
            force=True
        )

        page.wait_for_timeout(
            7000
        )

        # ----------------------------------------------------
        # CHECK LOGIN ERROR
        # ----------------------------------------------------

        body_text = ""

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:

            pass

        lower_body = (
            body_text.lower()
        )

        if (
            "invalid password"
            in lower_body
            or
            "invalid private key"
            in lower_body
            or
            "login failed"
            in lower_body
        ):

            raise RuntimeError(
                "Serey rejected login credentials."
            )

        print(
            "✅ LOGGED INTO SEREY SUCCESSFULLY!",
            flush=True
        )

        print(
            f"  - Current URL after login: "
            f"{page.url}",
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

    print(
        f"Steemit username: @{STEEM_USERNAME}",
        flush=True
    )

    print(
        f"Serey login: {SEREY_LOGIN}",
        flush=True
    )

    if PEXELS_API_KEY:

        print(
            "Pexels API key: AVAILABLE",
            flush=True
        )

    else:

        print(
            "Pexels API key: NOT AVAILABLE",
            flush=True
        )

    # --------------------------------------------------------
    # LOAD SYNCED POSTS
    # --------------------------------------------------------

    synced_posts = (
        load_synced_posts()
    )

    print(
        f"Previously synced posts: "
        f"{len(synced_posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # FETCH POSTS
    # --------------------------------------------------------

    posts = get_recent_posts()

    print(
        f"Total posts fetched: "
        f"{len(posts)}",
        flush=True
    )

    # --------------------------------------------------------
    # FIND UNSYNCED
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # POSTS FOR THIS RUN
    # --------------------------------------------------------

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

        if not login_to_serey(
            page
        ):

            browser.close()

            return

        # ----------------------------------------------------
        # PUBLISH POSTS
        # ----------------------------------------------------

        for post in new_posts_to_run:

            post_id = (
                f'{post["author"]}/'
                f'{post["permlink"]}'
            )

            print(
                "\n" + "-" * 60,
                flush=True
            )

            print(
                f"Processing: {post_id}",
                flush=True
            )

            result = publish_to_serey(
                page,
                post
            )

            # ------------------------------------------------
            # SAVE ONLY AFTER VERIFIED SUCCESS
            # ------------------------------------------------

            if result.get(
                "success"
            ):

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
                    f"⚠️ NOT saved as synced: "
                    f"{post_id}",
                    flush=True
                )

        # ----------------------------------------------------
        # CLOSE BROWSER
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


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
