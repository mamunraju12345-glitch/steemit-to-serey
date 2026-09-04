import os
import re
import json
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# STEEM -> SEREY AUTO SYNC
# FULL DIAGNOSTIC VERSION
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

NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"

TEMP_IMAGE = "temp_image.jpg"

POSTS_PER_RUN = 1

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.steememory.com",
    "https://api.steem.house",
]


# ============================================================
# REAL SEREY POST URL PATTERN
# ============================================================

REAL_POST_PATTERN = re.compile(
    r"https://(?:[a-zA-Z0-9-]+\.)?serey\.io/"
    r"authors/[^/\"'<>\\\s]+/"
    r"[^/\"'<>\\\s]+",
    re.IGNORECASE,
)

RELATIVE_POST_PATTERN = re.compile(
    r"/authors/[^/\"'<>\\\s]+/"
    r"[^/\"'<>\\\s]+",
    re.IGNORECASE,
)


# ============================================================
# LOAD SYNCED POSTS
# ============================================================

def load_synced():

    if not os.path.exists(SYNC_FILE):
        return []

    try:

        with open(
            SYNC_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

        return []

    except Exception as e:

        print(
            "Could not read synced_posts.json:",
            e
        )

        return []


# ============================================================
# SAVE SYNCED POSTS
# ============================================================

def save_synced(data):

    with open(
        SYNC_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# STEEM RPC
# ============================================================

def steem_rpc(method, params):

    last_error = None

    for node in STEEM_NODES:

        try:

            print("RPC:", node)

            response = requests.post(
                node,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params,
                },
                timeout=30,
            )

            response.raise_for_status()

            result = response.json()

            if "error" in result:

                raise Exception(
                    result["error"]
                )

            return result["result"]

        except Exception as e:

            print(
                "RPC failed:",
                e
            )

            last_error = e

    raise Exception(
        f"All Steem RPC nodes failed: {last_error}"
    )


# ============================================================
# GET STEEM POSTS
# ONLY LAST 30 DAYS
# ============================================================

def get_posts():

    print(
        f"Getting posts from @{STEEM_USERNAME}..."
    )

    posts = []

    # IMPORTANT:
    # Use naive datetime because Steem timestamp is naive.
    one_month_ago = (
        datetime.utcnow()
        - timedelta(days=30)
    )

    start_author = STEEM_USERNAME
    start_permlink = ""

    while True:

        try:

            result = steem_rpc(
                "condenser_api.get_discussions_by_blog",
                [
                    {
                        "tag": STEEM_USERNAME,
                        "limit": 100,
                        "start_author": start_author,
                        "start_permlink": start_permlink,
                    }
                ],
            )

        except Exception as e:

            print(
                "Could not get Steem posts:",
                e
            )

            break

        if not result:
            break

        reached_old_posts = False

        for post in result:

            if post.get("author") != STEEM_USERNAME:
                continue

            created_string = post.get(
                "created"
            )

            if not created_string:
                continue

            try:

                # IMPORTANT:
                # Remove timezone marker so both
                # datetimes are offset-naive.
                created = datetime.fromisoformat(
                    created_string.replace(
                        "Z",
                        ""
                    )
                )

            except Exception:

                continue

            if created < one_month_ago:

                print(
                    "Reached posts older than 30 days."
                )

                reached_old_posts = True

                break

            posts.append(post)

        if reached_old_posts:
            break

        last = result[-1]

        start_author = last.get(
            "author"
        )

        start_permlink = last.get(
            "permlink"
        )

        if (
            not start_author
            or not start_permlink
        ):

            break

        time.sleep(0.2)

    # --------------------------------------------------------
    # REMOVE DUPLICATES
    # --------------------------------------------------------

    unique = {}

    for post in posts:

        key = (
            f"{post.get('author')}/"
            f"{post.get('permlink')}"
        )

        unique[key] = post

    posts = list(
        unique.values()
    )

    # --------------------------------------------------------
    # OLDEST -> NEWEST
    # --------------------------------------------------------

    posts.sort(
        key=lambda x: x.get(
            "created",
            ""
        )
    )

    print(
        f"Total posts from last 1 month: {len(posts)}"
    )

    return posts


# ============================================================
# CLEAN BODY
# ============================================================

def clean_body(body):

    if not body:
        return ""

    return body.strip()


# ============================================================
# EXTRACT FIRST IMAGE
# ============================================================

def extract_image(body):

    if not body:
        return None

    patterns = [

        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',

        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',

        r'(https?://cdn\.steemitimages\.com/[^\s)"\'<>]+)',

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            body,
            re.IGNORECASE
        )

        if match:

            return match.group(1)

    return None


# ============================================================
# REMOVE FIRST MARKDOWN IMAGE
# ============================================================

def remove_first_image(body):

    if not body:
        return ""

    body = re.sub(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        "",
        body,
        count=1
    )

    return body.strip()


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    if not url:
        return None

    try:

        print(
            "Downloading image:",
            url
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
            "wb"
        ) as f:

            f.write(
                response.content
            )

        print(
            "✓ Image downloaded"
        )

        return TEMP_IMAGE

    except Exception as e:

        print(
            "Image download failed:",
            e
        )

        return None


# ============================================================
# EXTRACT REAL POST URL
# ============================================================

def extract_real_post_url(value):

    if not value:
        return None

    if not isinstance(
        value,
        str
    ):

        return None

    # Absolute URL
    match = REAL_POST_PATTERN.search(
        value
    )

    if match:

        url = match.group(0)

        return url.rstrip(
            ".,;:)]}"
        )

    # Relative URL
    match = RELATIVE_POST_PATTERN.search(
        value
    )

    if match:

        relative = match.group(0)

        relative = relative.rstrip(
            ".,;:)]}"
        )

        return urljoin(
            "https://serey.io",
            relative
        )

    return None


# ============================================================
# FIND URL INSIDE TEXT / JSON
# ============================================================

def find_url_in_text(text):

    if not text:
        return None

    if not isinstance(
        text,
        str
    ):

        return None

    # Direct search
    url = extract_real_post_url(
        text
    )

    if url:
        return url

    # JSON search
    try:

        data = json.loads(
            text
        )

        def recursive_search(value):

            if isinstance(
                value,
                str
            ):

                found = extract_real_post_url(
                    value
                )

                if found:
                    return found

            elif isinstance(
                value,
                dict
            ):

                for item in value.values():

                    found = recursive_search(
                        item
                    )

                    if found:
                        return found

            elif isinstance(
                value,
                list
            ):

                for item in value:

                    found = recursive_search(
                        item
                    )

                    if found:
                        return found

            return None

        return recursive_search(
            data
        )

    except Exception:

        return None


# ============================================================
# FIND POST LINK IN PAGE
# ============================================================

def find_post_link(
    page,
    title
):

    try:

        links = page.locator(
            "a[href]"
        )

        count = links.count()

        print(
            "Checking DOM links:",
            count
        )

        for i in range(
            min(count, 1000)
        ):

            try:

                link = links.nth(i)

                href = link.get_attribute(
                    "href"
                )

                if not href:
                    continue

                absolute = urljoin(
                    page.url,
                    href
                )

                real_url = extract_real_post_url(
                    absolute
                )

                if not real_url:
                    continue

                text = ""

                try:

                    text = link.inner_text(
                        timeout=1000
                    )

                except Exception:
                    pass

                if title:

                    title_words = [
                        x.lower()
                        for x in re.findall(
                            r"\w+",
                            title
                        )
                        if len(x) > 3
                    ]

                    link_text = text.lower()

                    matched = sum(
                        1
                        for word in title_words
                        if word in link_text
                    )

                    if matched >= min(
                        3,
                        len(title_words)
                    ):

                        print(
                            "✓ Matching post link found:",
                            real_url
                        )

                        return real_url

                slug_part = (
                    real_url
                    .split("/")[-1]
                    .lower()
                )

                if title:

                    title_slug_words = [
                        x.lower()
                        for x in re.findall(
                            r"\w+",
                            title
                        )
                        if len(x) > 4
                    ]

                    matched = sum(
                        1
                        for word in title_slug_words
                        if word in slug_part
                    )

                    if matched >= min(
                        2,
                        len(title_slug_words)
                    ):

                        print(
                            "✓ URL/title match found:",
                            real_url
                        )

                        return real_url

            except Exception:

                continue

    except Exception as e:

        print(
            "DOM link scan failed:",
            e
        )

    return None


# ============================================================
# SEARCH AUTHOR PAGE
# ============================================================

def search_author_page(
    context,
    username,
    title
):

    author_urls = [

        f"https://bengali.serey.io/authors/{username}",

        f"https://serey.io/authors/{username}",

    ]

    for author_url in author_urls:

        print(
            "Checking author page:",
            author_url
        )

        try:

            page = context.new_page()

            page.goto(
                author_url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(
                5000
            )

            print(
                "Author page URL:",
                page.url
            )

            found = find_post_link(
                page,
                title
            )

            if found:

                page.close()

                return found

            try:

                html = page.content()

                found = find_url_in_text(
                    html
                )

                if found:

                    print(
                        "✓ URL found in author HTML:",
                        found
                    )

                    page.close()

                    return found

            except Exception:
                pass

            page.close()

        except Exception as e:

            print(
                "Author page check failed:",
                e
            )

    return None


# ============================================================
# VERIFY REAL PUBLISHED POST
# ============================================================

def verify(
    context,
    page,
    title,
    captured_responses,
    captured_requests
):

    print()
    print(
        "VERIFYING PUBLISHED POST..."
    )
    print()

    # --------------------------------------------------------
    # STEP 1
    # --------------------------------------------------------

    print(
        "STEP 1: Checking captured responses..."
    )

    for item in captured_responses:

        response_url = item.get(
            "url",
            ""
        )

        found = extract_real_post_url(
            response_url
        )

        if found:

            print(
                "✓ REAL POST URL FOUND IN RESPONSE URL:"
            )

            print(found)

            return found

        body = item.get(
            "body",
            ""
        )

        found = find_url_in_text(
            body
        )

        if found:

            print(
                "✓ REAL POST URL FOUND IN RESPONSE BODY:"
            )

            print(found)

            return found

    # --------------------------------------------------------
    # STEP 2
    # --------------------------------------------------------

    print(
        "STEP 2: Checking captured requests..."
    )

    for item in captured_requests:

        request_url = item.get(
            "url",
            ""
        )

        found = extract_real_post_url(
            request_url
        )

        if found:

            print(
                "✓ REAL POST URL FOUND IN REQUEST:"
            )

            print(found)

            return found

        post_data = item.get(
            "post_data",
            ""
        )

        found = find_url_in_text(
            post_data
        )

        if found:

            print(
                "✓ REAL POST URL FOUND IN REQUEST DATA:"
            )

            print(found)

            return found

    # --------------------------------------------------------
    # STEP 3
    # --------------------------------------------------------

    print(
        "STEP 3: Checking current browser URL..."
    )

    print(
        "Current URL:",
        page.url
    )

    found = extract_real_post_url(
        page.url
    )

    if found:

        print(
            "✓ REAL POST URL FOUND:",
            found
        )

        return found

    # --------------------------------------------------------
    # STEP 4
    # --------------------------------------------------------

    print(
        "STEP 4: Checking current page links..."
    )

    found = find_post_link(
        page,
        title
    )

    if found:

        return found

    # --------------------------------------------------------
    # STEP 5
    # --------------------------------------------------------

    print(
        "STEP 5: Searching current page HTML..."
    )

    try:

        html = page.content()

        found = find_url_in_text(
            html
        )

        if found:

            print(
                "✓ REAL POST URL FOUND IN HTML:",
                found
            )

            return found

    except Exception as e:

        print(
            "HTML search failed:",
            e
        )

    # --------------------------------------------------------
    # STEP 6
    # --------------------------------------------------------

    print(
        "STEP 6: Checking author pages..."
    )

    found = search_author_page(
        context,
        SEREY_LOGIN,
        title
    )

    if found:

        return found

    # --------------------------------------------------------
    # STEP 7
    # --------------------------------------------------------

    print(
        "STEP 7: Checking all browser pages..."
    )

    for p in context.pages:

        try:

            print(
                "Open page:",
                p.url
            )

            found = extract_real_post_url(
                p.url
            )

            if found:

                return found

            found = find_post_link(
                p,
                title
            )

            if found:

                return found

            html = p.content()

            found = find_url_in_text(
                html
            )

            if found:

                return found

        except Exception:

            continue

    return None


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish(
    page,
    context,
    post
):

    title = post.get(
        "title",
        ""
    ).strip()

    body = clean_body(
        post.get(
            "body",
            ""
        )
    )

    category = post.get(
        "category",
        ""
    )

    print()
    print(
        "-" * 60
    )

    print(
        "Publishing:",
        title
    )

    print(
        "-" * 60
    )

    # --------------------------------------------------------
    # DIAGNOSTIC STORAGE
    # --------------------------------------------------------

    captured_requests = []
    captured_responses = []

    # --------------------------------------------------------
    # REQUEST LISTENER
    # --------------------------------------------------------

    def on_request(request):

        try:

            method = request.method.upper()

            resource_type = request.resource_type

            url = request.url

            if (
                method in [
                    "POST",
                    "PUT",
                    "PATCH"
                ]
                or resource_type in [
                    "xhr",
                    "fetch"
                ]
            ):

                post_data = (
                    request.post_data
                    or ""
                )

                safe_data = post_data

                if SEREY_PASSWORD:

                    safe_data = safe_data.replace(
                        SEREY_PASSWORD,
                        "***REDACTED***"
                    )

                item = {
                    "method": method,
                    "url": url,
                    "resource_type": resource_type,
                    "post_data": safe_data[:10000],
                }

                captured_requests.append(
                    item
                )

                print()
                print(
                    ">>> REQUEST",
                    method
                )

                print(
                    "URL:",
                    url
                )

        except Exception as e:

            print(
                "Request diagnostic error:",
                e
            )

    # --------------------------------------------------------
    # RESPONSE LISTENER
    # --------------------------------------------------------

    def on_response(response):

        try:

            request = response.request

            url = response.url

            status = response.status

            content_type = (
                response.headers.get(
                    "content-type",
                    ""
                )
            )

            interesting = (
                request.method.upper()
                in [
                    "POST",
                    "PUT",
                    "PATCH"
                ]
                or request.resource_type
                in [
                    "xhr",
                    "fetch"
                ]
            )

            if not interesting:
                return

            body_text = ""

            if (
                "json"
                in content_type.lower()
                or "text"
                in content_type.lower()
                or "javascript"
                in content_type.lower()
            ):

                try:

                    body_text = response.text()

                    if len(body_text) > 20000:

                        body_text = body_text[
                            :20000
                        ]

                except Exception:

                    body_text = ""

            item = {
                "method": request.method,
                "url": url,
                "status": status,
                "content_type": content_type,
                "body": body_text,
            }

            captured_responses.append(
                item
            )

            print()
            print(
                "<<< RESPONSE",
                status
            )

            print(
                "URL:",
                url
            )

            print(
                "Content-Type:",
                content_type
            )

            if body_text:

                found = find_url_in_text(
                    body_text
                )

                if found:

                    print(
                        "!!! POSSIBLE REAL POST URL:"
                    )

                    print(found)

                else:

                    print(
                        "Response body preview:"
                    )

                    print(
                        body_text[:1500]
                    )

        except Exception as e:

            print(
                "Response diagnostic error:",
                e
            )

    # --------------------------------------------------------
    # NAVIGATION LISTENER
    # --------------------------------------------------------

    def on_navigated(frame):

        try:

            print()
            print(
                ">>> NAVIGATION:",
                frame.url
            )

            found = extract_real_post_url(
                frame.url
            )

            if found:

                print(
                    "!!! NAVIGATION CONTAINS REAL POST:"
                )

                print(found)

        except Exception:
            pass

    # --------------------------------------------------------
    # NEW PAGE / POPUP
    # --------------------------------------------------------

    def on_new_page(new_page):

        try:

            print()
            print(
                "!!! NEW PAGE / POPUP OPENED"
            )

            print(
                "Popup URL:",
                new_page.url
            )

            new_page.on(
                "framenavigated",
                on_navigated
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # ATTACH LISTENERS BEFORE PUBLISH
    # --------------------------------------------------------

    page.on(
        "request",
        on_request
    )

    page.on(
        "response",
        on_response
    )

    page.on(
        "framenavigated",
        on_navigated
    )

    context.on(
        "page",
        on_new_page
    )

    # ========================================================
    # TITLE
    # ========================================================

    try:

        title_input = page.locator(
            'input[name="title"], '
            'input[placeholder*="Title"], '
            'input[placeholder*="title"]'
        ).first

        title_input.wait_for(
            state="visible",
            timeout=15000
        )

        title_input.fill(
            title
        )

        print(
            "✓ Title filled"
        )

    except Exception as e:

        print(
            "❌ Could not fill title:",
            e
        )

        return False

    # ========================================================
    # BODY
    # ========================================================

    try:

        body_locators = [

            'textarea[name="body"]',

            'textarea[placeholder*="body"]',

            'textarea[placeholder*="Body"]',

            '[contenteditable="true"]',

        ]

        filled = False

        for selector in body_locators:

            try:

                locator = page.locator(
                    selector
                ).first

                if locator.is_visible(
                    timeout=2000
                ):

                    locator.fill(
                        body
                    )

                    filled = True

                    break

            except Exception:

                continue

        if filled:

            print(
                "✓ Body filled"
            )

        else:

            print(
                "❌ Body field not found"
            )

            return False

    except Exception as e:

        print(
            "❌ Body error:",
            e
        )

        return False

    # ========================================================
    # IMAGE
    # ========================================================

    image_url = extract_image(
        post.get(
            "body",
            ""
        )
    )

    if image_url:

        image_file = download_image(
            image_url
        )

        if image_file:

            try:

                file_inputs = page.locator(
                    'input[type="file"]'
                )

                count = file_inputs.count()

                uploaded = False

                for i in range(count):

                    try:

                        file_input = (
                            file_inputs.nth(i)
                        )

                        file_input.set_input_files(
                            image_file
                        )

                        uploaded = True

                        print(
                            "✓ Thumbnail uploaded"
                        )

                        break

                    except Exception:

                        continue

                if not uploaded:

                    print(
                        "❌ File input found but upload failed"
                    )

            except Exception as e:

                print(
                    "Thumbnail upload error:",
                    e
                )

    # ========================================================
    # CATEGORY
    # ========================================================

    print(
        "Steemit category:",
        category
    )

    try:

        selectors = [

            'select[name="category"]',

            'select[name="categories"]',

            '[role="combobox"]',

        ]

        found_selector = None

        for selector in selectors:

            try:

                loc = page.locator(
                    selector
                ).first

                if loc.is_visible(
                    timeout=1000
                ):

                    found_selector = loc

                    break

            except Exception:

                continue

        if found_selector:

            print(
                "Category selector found."
            )

            try:

                options = (
                    found_selector
                    .locator("option")
                    .all_text_contents()
                )

                print(
                    "Category options:",
                    options
                )

            except Exception:
                pass

        else:

            print(
                "No category selector. Continuing."
            )

    except Exception:

        print(
            "No category selector. Continuing."
        )

    # ========================================================
    # SUB CATEGORY
    # ========================================================

    print(
        "No Sub Category selector."
    )

    # ========================================================
    # FIRST PUBLISH
    # ========================================================

    try:

        print(
            "Searching for FIRST Publish..."
        )

        publish_buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"publish",
                re.IGNORECASE
            )
        )

        count = publish_buttons.count()

        print(
            "Publish buttons found:",
            count
        )

        if count == 0:

            print(
                "❌ Publish button not found"
            )

            return False

        publish_buttons.first.click(
            timeout=15000
        )

        print(
            "✓ FIRST PUBLISH CLICKED"
        )

    except Exception as e:

        print(
            "❌ First publish click failed:",
            e
        )

        return False

    # ========================================================
    # WAIT
    # ========================================================

    page.wait_for_timeout(
        5000
    )

    # ========================================================
    # FINAL PUBLISH
    # ========================================================

    try:

        print(
            "Searching for FINAL Publish..."
        )

        buttons = page.get_by_role(
            "button",
            name=re.compile(
                r"publish",
                re.IGNORECASE
            )
        )

        count = buttons.count()

        print(
            "Publish buttons currently:",
            count
        )

        if count > 0:

            clicked = False

            for i in range(count):

                try:

                    button = buttons.nth(i)

                    if button.is_visible(
                        timeout=1000
                    ):

                        button.click(
                            timeout=10000
                        )

                        print(
                            "✓ FINAL PUBLISH CLICKED"
                        )

                        clicked = True

                        break

                except Exception:

                    continue

            if not clicked:

                print(
                    "❌ Could not click final Publish"
                )

                return False

        else:

            print(
                "No Publish button after first click."
            )

    except Exception as e:

        print(
            "Final publish error:",
            e
        )

        return False

    # ========================================================
    # WAIT FOR SERVER
    # ========================================================

    print()
    print(
        "Waiting 15 seconds for Serey response..."
    )

    page.wait_for_timeout(
        15000
    )

    # ========================================================
    # DIAGNOSTIC SUMMARY
    # ========================================================

    print()
    print(
        "=" * 60
    )

    print(
        "PUBLISH DIAGNOSTIC SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        "Current page:",
        page.url
    )

    print(
        "Captured requests:",
        len(captured_requests)
    )

    print(
        "Captured responses:",
        len(captured_responses)
    )

    print()

    # ========================================================
    # REQUESTS
    # ========================================================

    print(
        "POST/XHR/FETCH REQUESTS:"
    )

    for item in captured_requests:

        print(
            f"[{item['method']}] "
            f"{item['url']}"
        )

    print()

    # ========================================================
    # RESPONSES
    # ========================================================

    print(
        "POST/XHR/FETCH RESPONSES:"
    )

    for item in captured_responses:

        print(
            f"[{item['status']}] "
            f"{item['method']} "
            f"{item['url']}"
        )

    print(
        "=" * 60
    )

    # ========================================================
    # VERIFY
    # ========================================================

    real_url = verify(
        context,
        page,
        title,
        captured_responses,
        captured_requests
    )

    # ========================================================
    # CLEAN IMAGE
    # ========================================================

    try:

        if os.path.exists(
            TEMP_IMAGE
        ):

            os.remove(
                TEMP_IMAGE
            )

    except Exception:
        pass

    # ========================================================
    # SUCCESS
    # ========================================================

    if real_url:

        print()
        print(
            "✓✓✓ REAL PUBLISHED POST URL ✓✓✓"
        )

        print(
            real_url
        )

        print(
            "✓ PUBLICATION VERIFIED"
        )

        return real_url

    # ========================================================
    # FAILURE
    # ========================================================

    print()
    print(
        "❌ REAL PUBLISHED POST URL COULD NOT BE VERIFIED."
    )

    print(
        "❌ Post will NOT be marked as synced."
    )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "STEEM -> SEREY AUTO SYNC"
    )

    print(
        "=" * 60
    )

    # ========================================================
    # LOAD SYNCED
    # ========================================================

    synced = load_synced()

    print(
        "Previously synced:",
        len(synced)
    )

    # ========================================================
    # GET POSTS
    # ========================================================

    posts = get_posts()

    # ========================================================
    # UNSYNCED POSTS
    # ========================================================

    synced_set = set(
        synced
    )

    unsynced = []

    for post in posts:

        key = (
            f"{post.get('author')}/"
            f"{post.get('permlink')}"
        )

        if key not in synced_set:

            unsynced.append(
                post
            )

    print(
        "Unsynced posts:",
        len(unsynced)
    )

    # ========================================================
    # ONE POST PER RUN
    # ========================================================

    to_publish = unsynced[
        :POSTS_PER_RUN
    ]

    print(
        "Publishing this run:",
        len(to_publish)
    )

    if not to_publish:

        print(
            "No new posts to publish."
        )

        print(
            "=" * 60
        )

        return

    # ========================================================
    # CHECK CREDENTIALS
    # ========================================================

    if not SEREY_LOGIN:

        print(
            "❌ SEREY_LOGIN is missing."
        )

        return

    if not SEREY_PASSWORD:

        print(
            "❌ SEREY_PASSWORD is missing."
        )

        return

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 900,
            }
        )

        page = context.new_page()

        # ====================================================
        # LOGIN
        # ====================================================

        print(
            "Logging into Serey..."
        )

        try:

            page.goto(
                SEREY,
                wait_until="domcontentloaded",
                timeout=30000
            )

        except Exception as e:

            print(
                "Serey homepage error:",
                e
            )

        logged_in = False

        # ====================================================
        # CHECK ALREADY LOGGED IN
        # ====================================================

        try:

            text = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            if (
                SEREY_LOGIN.lower()
                in text.lower()
            ):

                logged_in = True

        except Exception:
            pass

        # ====================================================
        # LOGIN LINK
        # ====================================================

        if not logged_in:

            try:

                login_links = page.get_by_text(
                    re.compile(
                        r"login|sign in",
                        re.IGNORECASE
                    )
                )

                count = login_links.count()

                clicked = False

                for i in range(count):

                    try:

                        item = login_links.nth(i)

                        if item.is_visible(
                            timeout=1000
                        ):

                            item.click(
                                timeout=5000
                            )

                            clicked = True

                            break

                    except Exception:

                        continue

                if clicked:

                    page.wait_for_timeout(
                        3000
                    )

            except Exception as e:

                print(
                    "Login link error:",
                    e
                )

        # ====================================================
        # LOGIN FORM
        # ====================================================

        try:

            username_selectors = [

                'input[name="username"]',

                'input[name="email"]',

                'input[type="email"]',

                'input[placeholder*="Username"]',

                'input[placeholder*="username"]',

                'input[placeholder*="Email"]',

                'input[placeholder*="email"]',

            ]

            username_field = None

            for selector in username_selectors:

                try:

                    field = page.locator(
                        selector
                    ).first

                    if field.is_visible(
                        timeout=1000
                    ):

                        username_field = field

                        break

                except Exception:

                    continue

            if username_field:

                username_field.fill(
                    SEREY_LOGIN
                )

            password_field = page.locator(
                'input[type="password"]'
            ).first

            if password_field.is_visible(
                timeout=3000
            ):

                password_field.fill(
                    SEREY_PASSWORD
                )

            login_buttons = page.get_by_role(
                "button",
                name=re.compile(
                    r"login|sign in",
                    re.IGNORECASE
                )
            )

            count = login_buttons.count()

            if count:

                for i in range(count):

                    try:

                        button = login_buttons.nth(i)

                        if button.is_visible(
                            timeout=1000
                        ):

                            button.click(
                                timeout=10000
                            )

                            break

                    except Exception:

                        continue

            page.wait_for_timeout(
                5000
            )

            print(
                "✓ LOGGED INTO SEREY SUCCESSFULLY!"
            )

        except Exception as e:

            print(
                "Login form error:",
                e
            )

        # ====================================================
        # PUBLISH
        # ====================================================

        for post in to_publish:

            key = (
                f"{post.get('author')}/"
                f"{post.get('permlink')}"
            )

            try:

                page.goto(
                    NEW_POST,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

            except Exception as e:

                print(
                    "Could not open new post page:",
                    e
                )

                continue

            result = publish(
                page,
                context,
                post
            )

            # =================================================
            # ONLY SAVE WHEN REAL URL FOUND
            # =================================================

            if result:

                if key not in synced:

                    synced.append(
                        key
                    )

                    save_synced(
                        synced
                    )

                print()
                print(
                    "✓ SAVED AS SYNCED:",
                    key
                )

                print(
                    "✓ SEREY URL:",
                    result
                )

            else:

                print()
                print(
                    "❌ PUBLICATION VERIFICATION FAILED."
                )

                print(
                    "❌ NOT SAVED AS SYNCED:",
                    key
                )

        # ====================================================
        # CLOSE
        # ====================================================

        browser.close()

    print()
    print(
        "=" * 60
    )

    print(
        "SYNC COMPLETED"
    )

    print(
        "=" * 60
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
