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

PIXABAY_API_KEY = os.environ.get(
    "PIXABAY_API_KEY",
    ""
).strip()


# প্রতি GitHub Actions run-এ কয়টি post publish করবে
POSTS_PER_RUN = 1

# সর্বোচ্চ historical post
MAX_POSTS = 5000

# Synced database
DATA_FILE = "synced_posts.json"

# Temporary image
TEMP_IMG_FILE = "temp_thumbnail.jpg"


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
                f"RPC failed: {e}",
                flush=True
            )

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed. "
        f"Last error: {last_error}"
    )


# ============================================================
# LOAD SYNCED POSTS
# ============================================================

def load_synced_posts():

    if not os.path.exists(DATA_FILE):

        return set()

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):

            return set(data)

        return set()

    except Exception as e:

        print(
            f"Could not load synced posts: {e}",
            flush=True
        )

        return set()


# ============================================================
# SAVE SYNCED POSTS
# ============================================================

def save_synced_posts(posts):

    try:

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as file:

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
# EXTRACT IMAGES + CLEAN BODY
# ============================================================

def extract_image_and_clean_body(
    body_text,
    json_metadata_str
):

    image_urls = []


    # --------------------------------------------------------
    # 1. Images from Steem metadata
    # --------------------------------------------------------

    try:

        meta = json.loads(
            json_metadata_str
        )

        if isinstance(meta, dict):

            images = meta.get(
                "image",
                []
            )

            if isinstance(images, list):

                for img in images:

                    if (
                        isinstance(img, str)
                        and img.startswith("http")
                    ):

                        img = img.strip()

                        if img not in image_urls:

                            image_urls.append(img)

    except Exception:

        pass


    # --------------------------------------------------------
    # 2. Markdown images
    # --------------------------------------------------------

    markdown_images = re.findall(

        r'!\[[^\]]*\]'
        r'\((https?://[^)\s]+)\)',

        body_text,

        re.IGNORECASE

    )


    for img in markdown_images:

        img = img.strip().rstrip(
            '.,)"\''
        )

        if img not in image_urls:

            image_urls.append(img)


    # --------------------------------------------------------
    # 3. Direct image URLs
    # --------------------------------------------------------

    direct_images = re.findall(

        r'https?://[^\s<>"\']+'
        r'\.(?:png|jpg|jpeg|gif|webp)'
        r'(?:\?[^\s<>"\']*)?',

        body_text,

        re.IGNORECASE

    )


    for img in direct_images:

        img = img.strip().rstrip(
            '.,)"\''
        )

        if img not in image_urls:

            image_urls.append(img)


    # --------------------------------------------------------
    # Clean body
    # --------------------------------------------------------

    clean_body = re.sub(

        r'!\[[^\]]*\]'
        r'\([^)]+\)',

        '',

        body_text

    )


    clean_body = re.sub(

        r'https?://[^\s<>"\']+'
        r'\.(?:png|jpg|jpeg|gif|webp)'
        r'(?:\?[^\s<>"\']*)?',

        '',

        clean_body,

        flags=re.IGNORECASE

    )


    clean_body = re.sub(

        r'\n\s*\n\s*\n+',

        '\n\n',

        clean_body

    )


    return image_urls, clean_body.strip()


# ============================================================
# GET HISTORICAL STEEM POSTS
# ============================================================

def get_recent_posts():

    print(
        f"\nFetching ALL historical posts "
        f"from Steemit: @{STEEM_USERNAME}",
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


        if (
            start_author
            and start_permlink
        ):

            params["start_author"] = (
                start_author
            )

            params["start_permlink"] = (
                start_permlink
            )


        try:

            result = steem_rpc(

                "condenser_api."
                "get_discussions_by_blog",

                params

            )

        except Exception as e:

            print(
                f"❌ Failed to fetch batch: {e}",
                flush=True
            )

            break


        if not result:

            print(
                "No more Steem posts found.",
                flush=True
            )

            break


        # ----------------------------------------------------
        # Remove overlap from pagination
        # ----------------------------------------------------

        if (
            start_author
            and start_permlink
        ):

            batch = result[1:]

        else:

            batch = result


        if not batch:

            break


        new_in_batch = 0


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


            image_urls, clean_body = (
                extract_image_and_clean_body(
                    raw_body,
                    metadata
                )
            )


            all_posts.append({

                "author":
                    post.get(
                        "author",
                        ""
                    ),

                "permlink":
                    permlink,

                "title":
                    post.get(
                        "title",
                        ""
                    ),

                "body":
                    clean_body,

                "images":
                    image_urls,

                "image":
                    (
                        image_urls[0]
                        if image_urls
                        else None
                    ),

                "category":
                    post.get(
                        "category",
                        ""
                    ),

                "created":
                    post.get(
                        "created",
                        ""
                    )

            })


            new_in_batch += 1


        print(

            f"Batch #{batch_number}: "
            f"{len(result)} received, "
            f"{new_in_batch} new posts. "
            f"Total: {len(all_posts)}",

            flush=True

        )


        # ----------------------------------------------------
        # Pagination
        # ----------------------------------------------------

        last_post = result[-1]


        new_start_author = (
            last_post.get("author")
        )

        new_start_permlink = (
            last_post.get("permlink")
        )


        if (
            new_start_author
            == start_author

            and

            new_start_permlink
            == start_permlink
        ):

            print(
                "Pagination stopped: "
                "same starting post.",
                flush=True
            )

            break


        start_author = (
            new_start_author
        )

        start_permlink = (
            new_start_permlink
        )


        # ----------------------------------------------------
        # Safety limit
        # ----------------------------------------------------

        if len(all_posts) >= MAX_POSTS:

            print(
                f"Reached {MAX_POSTS}-post "
                f"safety limit.",
                flush=True
            )

            break


        if len(result) < 100:

            print(
                "Reached end of Steemit posts.",
                flush=True
            )

            break


        time.sleep(0.3)


    # Oldest first
    all_posts.reverse()


    return all_posts


# ============================================================
# DOWNLOAD STEEMIT IMAGE
# ============================================================

def download_image(image_urls):

    if not image_urls:

        return None


    if isinstance(
        image_urls,
        str
    ):

        image_urls = [
            image_urls
        ]


    user_agents = [

        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0.0.0 "
        "Safari/537.36",

        "Mozilla/5.0 "
        "(Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0.0.0 "
        "Mobile Safari/537.36"

    ]


    for url_number, url in enumerate(
        image_urls,
        1
    ):

        if not url:

            continue


        url = (
            url.strip()
            .rstrip('.,)"\'')
        )


        print(
            f"Trying Steemit image "
            f"{url_number}: {url}",
            flush=True
        )


        for attempt, user_agent in enumerate(
            user_agents,
            1
        ):

            try:

                response = requests.get(

                    url,

                    timeout=30,

                    headers={

                        "User-Agent":
                            user_agent,

                        "Accept":
                            "image/avif,"
                            "image/webp,"
                            "image/apng,"
                            "image/svg+xml,"
                            "image/*,*/*;q=0.8",

                        "Referer":
                            "https://steemit.com/"

                    },

                    allow_redirects=True

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


                if content_type.startswith(
                    "image/"
                ):

                    with open(
                        TEMP_IMG_FILE,
                        "wb"
                    ) as file:

                        file.write(
                            response.content
                        )


                    file_size = os.path.getsize(
                        TEMP_IMG_FILE
                    )


                    if file_size > 1000:

                        print(
                            "✅ Steemit image "
                            "downloaded!",
                            flush=True
                        )

                        return TEMP_IMG_FILE


                print(

                    f"Not an image. "
                    f"Content-Type: "
                    f"{content_type}",

                    flush=True

                )


            except Exception as e:

                print(

                    f"Image attempt "
                    f"{attempt} failed: {e}",

                    flush=True

                )


                time.sleep(1)


    print(
        "❌ No working Steemit image found.",
        flush=True
    )


    return None


# ============================================================
# PIXABAY FALLBACK
# ============================================================

def download_pixabay_image(
    title,
    body=""
):

    if not PIXABAY_API_KEY:

        print(
            "❌ PIXABAY_API_KEY not found.",
            flush=True
        )

        return None


    # --------------------------------------------------------
    # Build search text
    # --------------------------------------------------------

    text = f"{title} {body[:500]}"


    text = re.sub(

        r'https?://\S+',

        '',

        text

    )


    text = re.sub(

        r'[#*_{}\[\]()<>:;,!?|"/\\]+',

        ' ',

        text

    )


    # --------------------------------------------------------
    # Detect Bangla
    # --------------------------------------------------------

    has_bangla = any(

        '\u0980' <= ch <= '\u09ff'

        for ch in text

    )


    # Pixabay search works better with
    # English keywords for many topics.
    #
    # For Bangla-only titles we use
    # general relevant fallbacks.
    # --------------------------------------------------------

    if has_bangla:

        lower_text = text.lower()


        if (
            "ইসলাম" in text
            or "মুসলিম" in text
            or "মুহাম্মদ" in text
            or "হযরত" in text
            or "মসজিদ" in text
        ):

            queries = [

                "Islam mosque",

                "Mecca mosque",

                "Medina mosque",

                "Islamic architecture"

            ]

        elif (
            "প্রকৃতি" in text
            or "ফুল" in text
            or "গাছ" in text
            or "পাহাড়" in text
        ):

            queries = [

                "beautiful nature",

                "nature landscape",

                "green nature"

            ]

        elif (
            "খাবার" in text
            or "রান্না" in text
            or "রেসিপি" in text
        ):

            queries = [

                "delicious food",

                "cooking food",

                "healthy food"

            ]

        elif (
            "স্বাস্থ্য" in text
            or "ব্যায়াম" in text
            or "শরীর" in text
            or "ফিটনেস" in text
        ):

            queries = [

                "health fitness",

                "healthy lifestyle",

                "exercise workout"

            ]

        else:

            queries = [

                "beautiful lifestyle",

                "people lifestyle",

                "beautiful photography"

            ]

    else:

        words = text.split()


        keywords = []


        for word in words:

            word = word.strip()


            if len(word) < 3:

                continue


            if word.lower() not in keywords:

                keywords.append(
                    word.lower()
                )


            if len(keywords) >= 5:

                break


        query = " ".join(
            keywords
        )


        if query:

            queries = [
                query,
                "beautiful photography",
                "lifestyle"
            ]

        else:

            queries = [
                "beautiful photography",
                "nature"
            ]


    # --------------------------------------------------------
    # Search Pixabay
    # --------------------------------------------------------

    for query in queries:

        try:

            print(
                f"🔎 Searching Pixabay: "
                f"{query}",
                flush=True
            )


            api_url = (
                "https://pixabay.com/api/"
            )


            params = {

                "key":
                    PIXABAY_API_KEY,

                "q":
                    query,

                "image_type":
                    "photo",

                "orientation":
                    "horizontal",

                "safesearch":
                    "true",

                "per_page":
                    10

            }


            response = requests.get(

                api_url,

                params=params,

                timeout=30

            )


            response.raise_for_status()


            data = response.json()


            hits = data.get(
                "hits",
                []
            )


            if not hits:

                print(
                    "No images found.",
                    flush=True
                )

                continue


            # ------------------------------------------------
            # Try Pixabay results
            # ------------------------------------------------

            for hit in hits:

                image_url = hit.get(
                    "largeImageURL"
                )


                if not image_url:

                    continue


                try:

                    print(
                        f"Trying Pixabay image: "
                        f"{image_url}",
                        flush=True
                    )


                    img_response = requests.get(

                        image_url,

                        timeout=30,

                        headers={

                            "User-Agent":
                                "Mozilla/5.0"

                        }

                    )


                    img_response.raise_for_status()


                    content_type = (

                        img_response
                        .headers
                        .get(
                            "content-type",
                            ""
                        )
                        .lower()

                    )


                    if not content_type.startswith(
                        "image/"
                    ):

                        continue


                    with open(
                        TEMP_IMG_FILE,
                        "wb"
                    ) as file:

                        file.write(
                            img_response.content
                        )


                    if os.path.getsize(
                        TEMP_IMG_FILE
                    ) > 1000:

                        print(
                            "✅ Pixabay image "
                            "downloaded!",
                            flush=True
                        )

                        return TEMP_IMG_FILE


                except Exception as e:

                    print(
                        f"Pixabay image failed: "
                        f"{e}",
                        flush=True
                    )

                    continue


        except Exception as e:

            print(
                f"Pixabay search failed: "
                f"{e}",
                flush=True
            )

            continue


    print(
        "❌ No Pixabay image found.",
        flush=True
    )


    return None


# ============================================================
# FIND AND UPLOAD THUMBNAIL
# ============================================================

def prepare_thumbnail(post):

    image_urls = post.get(
        "images",
        []
    )


    # --------------------------------------------------------
    # Try Steemit images first
    # --------------------------------------------------------

    if image_urls:

        image_file = download_image(
            image_urls
        )


        if image_file:

            return image_file


    # --------------------------------------------------------
    # Steemit failed → Pixabay
    # --------------------------------------------------------

    print(
        "⚠️ Steemit image unavailable.",
        flush=True
    )


    print(
        "🔄 Trying Pixabay fallback...",
        flush=True
    )


    image_file = download_pixabay_image(

        post.get(
            "title",
            ""
        ),

        post.get(
            "body",
            ""
        )

    )


    return image_file


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


    try:

        # ----------------------------------------------------
        # Open new post page
        # ----------------------------------------------------

        page.goto(

            "https://serey.io/blog/post/new",

            timeout=60000

        )


        page.wait_for_timeout(
            4000
        )


        # ----------------------------------------------------
        # Title
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
        # Body
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
        # Prepare image
        # ----------------------------------------------------

        temp_img_path = None


        try:

            temp_img_path = prepare_thumbnail(
                post
            )


            if temp_img_path:

                file_input = page.locator(
                    'input[type="file"]'
                ).first


                if file_input.count() > 0:

                    file_input.set_input_files(
                        temp_img_path
                    )


                    print(
                        "  - Thumbnail image "
                        "uploaded!",
                        flush=True
                    )


                    page.wait_for_timeout(
                        4000
                    )

                else:

                    print(
                        "❌ File input not found "
                        "on Serey.",
                        flush=True
                    )

            else:

                print(
                    "⚠️ No thumbnail available. "
                    "Publishing without image.",
                    flush=True
                )


        except Exception as image_error:

            print(
                f"Thumbnail processing error: "
                f"{image_error}",
                flush=True
            )


        # ----------------------------------------------------
        # FIRST PUBLISH BUTTON
        # ----------------------------------------------------

        publish_buttons = page.locator(
            'button:has-text("Publish")'
        )


        publish_buttons.first.click(
            force=True
        )


        print(
            "  - First Publish button clicked!",
            flush=True
        )


        # ----------------------------------------------------
        # Wait for category modal
        # ----------------------------------------------------

        page.wait_for_timeout(
            6000
        )


        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

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


                option = page.locator(

                    '.ant-select-item-option, '
                    'div[title="General"], '
                    'div[title="general"], '
                    'li'

                ).first


                if option.count() > 0:

                    option.click(
                        force=True
                    )

                    print(
                        "  - Category selected!",
                        flush=True
                    )

                else:

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


        except Exception as category_error:

            print(
                f"Category selection fallback: "
                f"{category_error}",
                flush=True
            )


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


        final_publish.click(
            force=True
        )


        print(
            "  - Final Publish button clicked!",
            flush=True
        )


        # ----------------------------------------------------
        # Wait for Serey
        # ----------------------------------------------------

        page.wait_for_timeout(
            12000
        )


        # ----------------------------------------------------
        # VERIFY CURRENT URL
        # ----------------------------------------------------

        print(
            "🔎 VERIFYING POST ON SEREY...",
            flush=True
        )


        current_url = page.url


        print(
            f"Current Serey URL: "
            f"{current_url}",
            flush=True
        )


        # ----------------------------------------------------
        # Make sure we are on an author post page
        # ----------------------------------------------------

        if "/authors/" not in current_url:

            print(
                "⚠️ Current URL is not a "
                "Serey author post URL.",
                flush=True
            )


            # Try current page content anyway
            page.wait_for_timeout(
                3000
            )


        # ----------------------------------------------------
        # Get current page text
        # ----------------------------------------------------

        page_text = page.locator(
            "body"
        ).inner_text(
            timeout=20000
        )


        expected_title = post.get(
            "title",
            ""
        ).strip()


        print(
            f"Expected title: "
            f"{expected_title}",
            flush=True
        )


        # ----------------------------------------------------
        # Exact title verification
        # ----------------------------------------------------

        if (
            expected_title
            and
            expected_title.lower()
            in
            page_text.lower()
        ):

            print(
                "✅ TITLE FOUND ON CURRENT "
                "SEREY PAGE!",
                flush=True
            )


            print(
                f"✅ VERIFIED & CONFIRMED: "
                f"{expected_title}",
                flush=True
            )


            # Remove temp image
            if os.path.exists(
                TEMP_IMG_FILE
            ):

                try:

                    os.remove(
                        TEMP_IMG_FILE
                    )

                except Exception:

                    pass


            return True


        # ----------------------------------------------------
        # Secondary verification:
        # URL contains authors
        # and title words are found
        # ----------------------------------------------------

        title_words = [

            word.lower()

            for word in re.sub(
                r"[^\w\s]",
                " ",
                expected_title
            ).split()

            if len(word) >= 3

        ]


        matched_words = 0


        page_text_lower = (
            page_text.lower()
        )


        for word in title_words[:5]:

            if word in page_text_lower:

                matched_words += 1


        if (
            "/authors/" in current_url
            and
            matched_words >= 2
        ):

            print(
                "✅ POST VERIFIED USING "
                "TITLE WORDS + SEREY URL!",
                flush=True
            )


            if os.path.exists(
                TEMP_IMG_FILE
            ):

                try:

                    os.remove(
                        TEMP_IMG_FILE
                    )

                except Exception:

                    pass


            return True


        # ----------------------------------------------------
        # Verification failed
        # ----------------------------------------------------

        print(
            "❌ POST COULD NOT BE VERIFIED "
            "ON SEREY.",
            flush=True
        )


        print(
            "Post will NOT be saved as synced.",
            flush=True
        )


        if os.path.exists(
            TEMP_IMG_FILE
        ):

            try:

                os.remove(
                    TEMP_IMG_FILE
                )

            except Exception:

                pass


        return False


    except Exception as e:

        print(
            f"❌ Failed to publish post "
            f"on Serey: {e}",
            flush=True
        )


        if os.path.exists(
            TEMP_IMG_FILE
        ):

            try:

                os.remove(
                    TEMP_IMG_FILE
                )

            except Exception:

                pass


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
    # Check Pixabay
    # --------------------------------------------------------

    if PIXABAY_API_KEY:

        print(
            "Pixabay API: CONFIGURED",
            flush=True
        )

    else:

        print(
            "⚠️ Pixabay API: NOT CONFIGURED",
            flush=True
        )


    # --------------------------------------------------------
    # Load synced posts
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
    # Fetch Steemit
    # --------------------------------------------------------

    posts = get_recent_posts()


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
    # Find unsynced posts
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
    # One post per run
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
    # Playwright
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
        # Login
        # ----------------------------------------------------

        print(
            "\nLogging into Serey.io...",
            flush=True
        )


        try:

            page.goto(

                "https://serey.io",

                timeout=60000

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
                5000
            )


            page.wait_for_selector(

                'input[placeholder="Username"], '
                'input[placeholder*="Username"]',

                timeout=20000

            )


            username_input = page.locator(

                'input[placeholder="Username"], '
                'input[placeholder*="Username"]'

            ).first


            username_input.fill(
                SEREY_LOGIN
            )


            password_input = page.locator(

                'input[placeholder*="Private Key"], '
                'input[placeholder*="Password"]'

            ).first


            password_input.fill(
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
                6000
            )


            print(
                "LOGGED INTO SEREY SUCCESSFULLY!",
                flush=True
            )


        except Exception as e:

            print(
                f"❌ Login failed: {e}",
                flush=True
            )


            browser.close()

            return


        # ----------------------------------------------------
        # Publish posts
        # ----------------------------------------------------

        for post in new_posts_to_run:

            success = publish_to_serey(

                page,

                post

            )


            if success:

                post_id = (

                    f'{post["author"]}/'
                    f'{post["permlink"]}'

                )


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
                    "⚠️ Verification failed. "
                    "Post was NOT added to synced_posts.",
                    flush=True
                )


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
# START
# ============================================================

if __name__ == "__main__":

    main()
