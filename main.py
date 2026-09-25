import os
import json
import re
import time
import mimetypes
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, unquote

import requests
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ.get("STEEM_USERNAME", "").strip()

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"

POSTS_PER_RUN = 1
DAYS_LIMIT = 365

TEMP_IMAGE_PREFIX = "temp_image"

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
]

# Publish verification settings
PUBLISH_WAIT_SECONDS = 60
ACTIVITY_RETRIES = 4
ACTIVITY_WAIT_SECONDS = 5


# ============================================================
# REMOVE COOKIE / OVERLAYS
# ============================================================

def remove_overlays(page):
    try:
        page.evaluate("""
            const selectors = [
                '.no-cookie-notice-overlay',
                '[class*="cookie-notice"]',
                '[class*="cookie-banner"]'
            ];

            selectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => el.remove());
            });
        """)
    except Exception:
        pass


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
            r = requests.post(
                node,
                json=payload,
                timeout=20
            )

            r.raise_for_status()

            data = r.json()

            if "error" in data:
                raise Exception(data["error"])

            print(f"✓ RPC success: {node}", flush=True)

            return data["result"]

        except Exception as e:
            print(
                f"RPC {node} failed: {e}",
                flush=True
            )

    raise Exception("All Steem RPC nodes failed")


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

        return set()

    except Exception as e:
        print(
            f"⚠ Could not read {SYNC_FILE}: {e}",
            flush=True
        )

        return set()


def save_synced(data):
    temp_file = SYNC_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            sorted(data),
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp_file,
        SYNC_FILE
    )


# ============================================================
# THUMBNAIL + CLEAN BODY
# ============================================================

def extract_thumbnail_and_body(body, metadata):

    thumbnail = None

    try:
        meta = json.loads(
            metadata or "{}"
        )

        images = meta.get(
            "image",
            []
        )

        if isinstance(images, list):

            for x in images:

                if (
                    isinstance(x, str)
                    and x.startswith("http")
                ):
                    thumbnail = x
                    break

    except Exception:
        pass

    # Markdown image
    if not thumbnail:

        m = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)',
            body,
            re.I
        )

        if m:
            thumbnail = m.group(1)

    # HTML image
    if not thumbnail:

        m = re.search(
            r'<img[^>]+src=["\'](https?://[^"\'>\s]+)',
            body,
            re.I
        )

        if m:
            thumbnail = m.group(1)

    # Direct image URL
    if not thumbnail:

        m = re.search(
            r'(https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?)',
            body,
            re.I
        )

        if m:
            thumbnail = m.group(1)

    # Remove markdown images
    body = re.sub(
        r'!\[[^\]]*\]\(\s*https?://[^)\s]+\s*\)',
        '',
        body,
        flags=re.I
    )

    # Remove HTML images
    body = re.sub(
        r'<img\b[^>]*>',
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

    # Remove HTML
    body = re.sub(
        r'<[^>]+>',
        '',
        body
    )

    # Remove Markdown headings
    body = re.sub(
        r'^\s{0,3}#{1,6}\s*',
        '',
        body,
        flags=re.M
    )

    # Bold
    body = re.sub(
        r'\*\*(.*?)\*\*',
        r'\1',
        body,
        flags=re.S
    )

    # Italic
    body = re.sub(
        r'(?<!\*)\*(.*?)\*(?!\*)',
        r'\1',
        body,
        flags=re.S
    )

    # Markdown links
    body = re.sub(
        r'\[([^\]]+)\]\((https?://[^)]+)\)',
        r'\1',
        body,
        flags=re.I
    )

    lines = []

    for line in body.splitlines():

        stripped = line.strip()

        if not stripped:
            lines.append("")
            continue

        if re.fullmatch(
            r'https?://\S+',
            stripped,
            re.I
        ):
            continue

        lines.append(line)

    body = "\n".join(lines)

    body = re.sub(
        r'\n[ \t]*\n[ \t]*\n+',
        '\n\n',
        body
    )

    body = "\n".join(
        line.strip()
        for line in body.splitlines()
    )

    return body.strip(), thumbnail


def parse_steem_date(date_str):

    try:

        return datetime.strptime(
            date_str,
            "%Y-%m-%dT%H:%M:%S"
        ).replace(
            tzinfo=timezone.utc
        )

    except Exception:

        return None


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_posts():

    print(
        f"Collecting posts from @{STEEM_USERNAME} "
        f"for the last {DAYS_LIMIT} days...",
        flush=True
    )

    cutoff_date = (
        datetime.now(timezone.utc)
        - timedelta(days=DAYS_LIMIT)
    )

    print(
        f"Post cut-off date: "
        f"{cutoff_date.strftime('%Y-%m-%d')}",
        flush=True
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None

    reached_old = False

    while len(posts) < 5000 and not reached_old:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author:

            params["start_author"] = start_author
            params["start_permlink"] = start_permlink

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

            if not permlink:
                continue

            post_id = (
                f"{author}/{permlink}"
            )

            if post_id in seen:
                continue

            created_str = p.get(
                "created",
                ""
            )

            created_dt = parse_steem_date(
                created_str
            )

            if (
                created_dt
                and created_dt < cutoff_date
            ):
                reached_old = True
                break

            seen.add(post_id)

            body, thumbnail = (
                extract_thumbnail_and_body(
                    p.get("body", ""),
                    p.get(
                        "json_metadata",
                        "{}"
                    )
                )
            )

            posts.append({
                "id": post_id,
                "title": p.get(
                    "title",
                    ""
                ).strip(),
                "body": body,
                "thumbnail": thumbnail,
                "created": created_str,
                "category": p.get(
                    "category",
                    ""
                )
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

        if (
            len(result) < 100
            or reached_old
        ):
            break

        time.sleep(0.3)

    # Oldest → newest
    posts.reverse()

    print(
        f"Total posts collected from the last "
        f"{DAYS_LIMIT} days: {len(posts)}",
        flush=True
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
            f"Downloading cover thumbnail: {url}",
            flush=True
        )

        headers = {
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36",
            "Referer":
                "https://steemit.com/"
        }

        r = requests.get(
            url,
            timeout=25,
            headers=headers
        )

        r.raise_for_status()

        content_type = (
            r.headers
            .get("content-type", "")
            .lower()
        )

        ext = (
            mimetypes.guess_extension(
                content_type.split(";")[0]
            )
            or ".jpg"
        )

        if ext == ".jpe":
            ext = ".jpg"

        file_path = (
            f"{TEMP_IMAGE_PREFIX}{ext}"
        )

        with open(
            file_path,
            "wb"
        ) as f:
            f.write(r.content)

        print(
            f"✓ Cover image saved: "
            f"{file_path} "
            f"({len(r.content)} bytes)",
            flush=True
        )

        return file_path

    except Exception as e:

        print(
            f"❌ Cover image download failed: {e}",
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

    max_attempts = 3

    for attempt in range(
        1,
        max_attempts + 1
    ):

        print(
            f"\n--- Login Attempt "
            f"{attempt}/{max_attempts} ---",
            flush=True
        )

        try:

            page.goto(
                SEREY,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(5000)

            remove_overlays(page)

            logged_in_selectors = [
                f'a[href*="{SEREY_LOGIN}"]',
                'a[href*="/blog/post/new"]',
                'button:has-text("Write")',
                '.user-profile-header',
                '.ant-avatar'
            ]

            for sel in logged_in_selectors:

                try:

                    loc = page.locator(sel)

                    if (
                        loc.count() > 0
                        and loc.first.is_visible()
                    ):
                        print(
                            "✓ Detected existing session! "
                            "Already logged in.",
                            flush=True
                        )

                        return True

                except Exception:
                    continue

            login_buttons = page.locator(
                'a:has-text("Log in"), '
                'button:has-text("Log in"), '
                'a:has-text("Log In"), '
                'button:has-text("Log In"), '
                'button:has-text("লগ ইন"), '
                'a:has-text("লগ ইন")'
            )

            if (
                login_buttons.count() == 0
                or not login_buttons.first.is_visible()
            ):

                print(
                    "Navigating to /blog/post/new...",
                    flush=True
                )

                page.goto(
                    NEW_POST,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                page.wait_for_timeout(5000)

                remove_overlays(page)

            login_buttons = page.locator(
                'a:has-text("Log in"), '
                'button:has-text("Log in"), '
                'a:has-text("Log In"), '
                'button:has-text("Log In"), '
                'button:has-text("লগ ইন"), '
                'a:has-text("লগ ইন")'
            )

            if (
                login_buttons.count() > 0
                and login_buttons.first.is_visible()
            ):

                print(
                    "Clicking 'Log in' button...",
                    flush=True
                )

                login_buttons.first.click(
                    force=True
                )

                page.wait_for_timeout(4000)

            user_in = page.locator(
                '.ant-modal:visible '
                'input[placeholder*="Username" i], '
                'input[placeholder*="Username" i], '
                'input[placeholder*="ইউজারনেম" i], '
                'input[type="text"]:visible'
            ).first

            pass_in = page.locator(
                '.ant-modal:visible '
                'input[type="password"], '
                'input[placeholder*="Private Key" i], '
                'input[placeholder*="Password" i], '
                'input[type="password"]:visible'
            ).first

            user_in.wait_for(
                state="visible",
                timeout=30000
            )

            pass_in.wait_for(
                state="visible",
                timeout=30000
            )

            print(
                "Filling login credentials...",
                flush=True
            )

            user_in.fill(
                SEREY_LOGIN
            )

            page.wait_for_timeout(500)

            pass_in.fill(
                SEREY_PASSWORD
            )

            page.wait_for_timeout(500)

            submit_btn = page.locator(
                '.ant-modal:visible '
                'button:has-text("Log in"), '
                '.ant-modal:visible '
                'button:has-text("Log In"), '
                'button:has-text("Log in"), '
                'button:has-text("Log In")'
            ).last

            submit_btn.click(
                force=True,
                timeout=15000
            )

            page.wait_for_timeout(8000)

            remove_overlays(page)

            print(
                "✓ LOGGED INTO SEREY SUCCESSFULLY!",
                flush=True
            )

            return True

        except Exception as e:

            print(
                f"⚠ Login attempt {attempt} failed: {e}",
                flush=True
            )

            if attempt == max_attempts:

                save_debug(page)

                raise Exception(
                    "All Serey login attempts "
                    "failed permanently."
                )

            page.wait_for_timeout(4000)


# ============================================================
# URL HELPERS
# ============================================================

def normalize_url(url):

    if not url:
        return None

    url = str(url).strip()

    if not url:
        return None

    if url.startswith("//"):

        url = "https:" + url

    elif url.startswith("/"):

        url = SEREY + url

    elif not url.startswith("http"):

        return None

    return url.split("#")[0]


def is_real_post_url(url):

    url = normalize_url(url)

    if not url:
        return False

    try:

        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .split(":")[0]
        )

        path = parsed.path.rstrip("/")

        if not (
            host == "serey.io"
            or host == "www.serey.io"
            or host.endswith(".serey.io")
        ):
            return False

        bad_parts = [
            "/blog/post/new",
            "/my-activity",
            "/activity",
            "/profile",
            "/posts",
            "/followers",
            "/following",
            "/login",
            "/register"
        ]

        lower_path = path.lower()

        for bad in bad_parts:

            if bad in lower_path:
                return False

        m = re.match(
            r"^/authors/([^/]+)/([^/]+)$",
            path,
            re.I
        )

        if not m:
            return False

        username = (
            m.group(1)
            .replace("@", "")
            .lower()
        )

        post_id = (
            m.group(2)
            .lower()
        )

        expected_user = (
            SEREY_LOGIN
            .replace("@", "")
            .lower()
        )

        if username != expected_user:
            return False

        bad_ids = {
            "my-activity",
            "activity",
            "profile",
            "posts",
            "followers",
            "following",
            "write",
            "new"
        }

        if post_id in bad_ids:
            return False

        return True

    except Exception:

        return False


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = unquote(
        str(text)
    )

    text = text.lower()

    text = re.sub(
        r'\s+',
        ' ',
        text
    )

    text = re.sub(
        r'[^\w\s\-]',
        ' ',
        text,
        flags=re.UNICODE
    )

    text = re.sub(
        r'\s+',
        ' ',
        text
    )

    return text.strip()


def title_matches(target_title, candidate_text):

    target = normalize_text(
        target_title
    )

    candidate = normalize_text(
        candidate_text
    )

    if not target or not candidate:
        return False

    # Exact match
    if target in candidate:
        return True

    target_words = [
        x
        for x in target.split()
        if len(x) >= 3
    ]

    if not target_words:
        return False

    matched = sum(
        1
        for word in target_words
        if word in candidate
    )

    required = max(
        2,
        min(
            5,
            len(target_words)
        )
    )

    return matched >= required


# ============================================================
# NETWORK CAPTURE
# ============================================================

class NetworkCapture:

    def __init__(self):
        self.responses = []

    def attach(self, page):

        def on_response(response):

            try:

                url = response.url

                method = (
                    response.request.method
                    if response.request
                    else ""
                )

                status = response.status

                if (
                    method.upper()
                    in {"POST", "PUT", "PATCH"}
                    or "/api/" in url.lower()
                    or "global-api" in url.lower()
                ):

                    item = {
                        "url": url,
                        "method": method,
                        "status": status,
                        "text": ""
                    }

                    try:

                        content_type = (
                            response.headers
                            .get(
                                "content-type",
                                ""
                            )
                            .lower()
                        )

                        if (
                            "json" in content_type
                            or "/api/" in url.lower()
                        ):

                            try:

                                item["text"] = (
                                    response.text()[:30000]
                                )

                            except Exception:
                                pass

                    except Exception:
                        pass

                    self.responses.append(
                        item
                    )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )


# ============================================================
# EXTRACT URLS
# ============================================================

def extract_urls_from_text(text):

    found = []

    if not text:
        return found

    urls = re.findall(
        r'https?://[^\s"\'<>]+',
        text,
        re.I
    )

    for url in urls:

        url = url.rstrip(
            ".,;:)]}'\""
        )

        if is_real_post_url(url):

            found.append(
                url
            )

    return found


def collect_urls_from_json(obj):

    found = []

    if obj is None:
        return found

    if isinstance(obj, str):

        found.extend(
            extract_urls_from_text(obj)
        )

        matches = re.findall(
            r'["\'](\/authors\/[^"\']+)["\']',
            obj,
            re.I
        )

        for x in matches:

            candidate = normalize_url(x)

            if is_real_post_url(
                candidate
            ):
                found.append(
                    candidate
                )

        return found

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_lower = str(
                key
            ).lower()

            if any(
                word in key_lower
                for word in [
                    "url",
                    "link",
                    "slug",
                    "permalink",
                    "post",
                    "article"
                ]
            ):

                if isinstance(
                    value,
                    str
                ):

                    candidate = (
                        normalize_url(value)
                    )

                    if is_real_post_url(
                        candidate
                    ):
                        found.append(
                            candidate
                        )

                    found.extend(
                        extract_urls_from_text(
                            value
                        )
                    )

            found.extend(
                collect_urls_from_json(
                    value
                )
            )

        return found

    if isinstance(obj, list):

        for item in obj:

            found.extend(
                collect_urls_from_json(
                    item
                )
            )

    return found


def analyze_network_responses(
    capture,
    target_title=None
):

    print(
        "\n" + "=" * 60,
        flush=True
    )

    print(
        "PUBLISH NETWORK RESPONSES",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    real_urls = []

    for i, item in enumerate(
        capture.responses
    ):

        url = item.get(
            "url",
            ""
        )

        method = item.get(
            "method",
            ""
        )

        status = item.get(
            "status",
            ""
        )

        text = item.get(
            "text",
            ""
        )

        print(
            f"[{i+1}] "
            f"{method} "
            f"{status} "
            f"{url}",
            flush=True
        )

        if text:

            compact = re.sub(
                r"\s+",
                " ",
                text
            )

            print(
                f"    RESPONSE: "
                f"{compact[:1500]}",
                flush=True
            )

            real_urls.extend(
                extract_urls_from_text(
                    text
                )
            )

            try:

                data = json.loads(
                    text
                )

                real_urls.extend(
                    collect_urls_from_json(
                        data
                    )
                )

            except Exception:
                pass

    result = []

    for url in real_urls:

        if (
            url not in result
            and is_real_post_url(url)
        ):

            result.append(url)

    print(
        "=" * 60,
        flush=True
    )

    if result:

        print(
            "✓ REAL POST URL FOUND IN API:",
            flush=True
        )

        for url in result:
            print(
                url,
                flush=True
            )

    else:

        print(
            "No real post URL found in API responses.",
            flush=True
        )

    print(
        "=" * 60,
        flush=True
    )

    return result


# ============================================================
# FIND REAL POST LINKS
# ============================================================

def find_real_post_links(page):

    urls = []

    try:

        links = page.locator(
            'a[href]'
        )

        count = min(
            links.count(),
            1000
        )

        for i in range(count):

            try:

                href = (
                    links.nth(i)
                    .get_attribute("href")
                )

                candidate = normalize_url(
                    href
                )

                if is_real_post_url(
                    candidate
                ):

                    if candidate not in urls:

                        urls.append(
                            candidate
                        )

            except Exception:
                continue

    except Exception:
        pass

    return urls


# ============================================================
# FIND POST BY TITLE ON CURRENT PAGE
# ============================================================

def find_post_link_by_title(
    page,
    title
):

    print(
        f"Searching page for exact post title: "
        f"{title}",
        flush=True
    )

    candidates = []

    try:

        # First inspect links
        links = page.locator(
            'a[href]'
        )

        count = min(
            links.count(),
            1000
        )

        for i in range(count):

            try:

                link = links.nth(i)

                href = link.get_attribute(
                    "href"
                )

                candidate = normalize_url(
                    href
                )

                if not is_real_post_url(
                    candidate
                ):
                    continue

                text = ""

                try:
                    text = link.inner_text(
                        timeout=1000
                    )
                except Exception:
                    pass

                parent_text = ""

                try:
                    parent_text = link.locator(
                        "xpath=.."
                    ).inner_text(
                        timeout=1000
                    )
                except Exception:
                    pass

                combined = (
                    f"{text} {parent_text}"
                )

                if title_matches(
                    title,
                    combined
                ):

                    print(
                        f"✓ Matching post link found: "
                        f"{candidate}",
                        flush=True
                    )

                    return candidate

                candidates.append(
                    candidate
                )

            except Exception:
                continue

    except Exception:
        pass

    # Second method: inspect body text around title
    try:

        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

        if title_matches(
            title,
            body_text
        ):

            print(
                "✓ Target title exists on page.",
                flush=True
            )

            # Search links again and return
            # a candidate if only one/small set exists
            unique = []

            for x in candidates:

                if x not in unique:
                    unique.append(x)

            if len(unique) == 1:

                print(
                    f"✓ Single candidate accepted: "
                    f"{unique[0]}",
                    flush=True
                )

                return unique[0]

    except Exception:
        pass

    return None


# ============================================================
# VERIFY REAL POST PAGE
# ============================================================

def verify_real_post_page(
    page,
    url,
    title
):

    if not is_real_post_url(
        url
    ):
        return False

    print(
        f"Verifying candidate post URL: {url}",
        flush=True
    )

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        page.wait_for_timeout(5000)

        final_url = page.url

        print(
            f"Verification URL: {final_url}",
            flush=True
        )

        if not is_real_post_url(
            final_url
        ):

            print(
                "❌ Candidate URL failed URL validation.",
                flush=True
            )

            return False

        body_text = ""

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

        except Exception:
            pass

        if title_matches(
            title,
            body_text
        ):

            print(
                "✓ REAL PUBLISHED POST VERIFIED!",
                flush=True
            )

            print(
                f"✓ URL: {final_url}",
                flush=True
            )

            return True

        print(
            "❌ URL exists but target title "
            "could not be verified.",
            flush=True
        )

        return False

    except Exception as e:

        print(
            f"❌ Post page verification failed: {e}",
            flush=True
        )

        return False


# ============================================================
# ACTIVITY SEARCH
# ============================================================

def search_activity_for_post(
    page,
    title
):

    activity_url = (
        f"{SEREY}/authors/"
        f"{SEREY_LOGIN}/my-activity"
    )

    print(
        "Checking profile activity for "
        "the newly published post...",
        flush=True
    )

    for attempt in range(
        1,
        ACTIVITY_RETRIES + 1
    ):

        print(
            f"Activity check "
            f"{attempt}/{ACTIVITY_RETRIES}",
            flush=True
        )

        try:

            page.goto(
                activity_url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(
                ACTIVITY_WAIT_SECONDS * 1000
            )

            remove_overlays(page)

            # Try direct title matching
            candidate = find_post_link_by_title(
                page,
                title
            )

            if candidate:

                print(
                    f"✓ Target post found "
                    f"in activity: {candidate}",
                    flush=True
                )

                return [candidate]

            # Fallback: collect all real links
            links = find_real_post_links(
                page
            )

            if links:

                print(
                    f"Found {len(links)} real "
                    f"post links in activity.",
                    flush=True
                )

                # Verify candidates individually.
                # Limit to newest 20 links.
                for candidate in links[:20]:

                    print(
                        f"Testing activity candidate: "
                        f"{candidate}",
                        flush=True
                    )

                    if verify_real_post_page(
                        page,
                        candidate,
                        title
                    ):

                        return [candidate]

            print(
                "Target post not found yet.",
                flush=True
            )

            if attempt < ACTIVITY_RETRIES:

                print(
                    "Refreshing activity and "
                    "checking again...",
                    flush=True
                )

                page.wait_for_timeout(
                    3000
                )

        except Exception as e:

            print(
                f"Activity search attempt "
                f"{attempt} failed: {e}",
                flush=True
            )

            if attempt < ACTIVITY_RETRIES:

                page.wait_for_timeout(
                    3000
                )

    print(
        "No matching post found in activity.",
        flush=True
    )

    return []


# ============================================================
# CROP MODAL
# ============================================================

def close_crop_modal(page):

    try:

        remove_overlays(page)

        modals = page.locator(
            ".ant-modal-wrap:visible, "
            ".ant-modal:visible"
        )

        count = modals.count()

        if count == 0:
            return

        for i in range(count):

            modal = modals.nth(i)

            try:

                text = modal.inner_text(
                    timeout=1000
                ).lower()

            except Exception:

                text = ""

            if (
                "crop" in text
                or modal.locator(
                    '[data-testid="cropper"]'
                ).count() > 0
            ):

                buttons = modal.locator(
                    "button"
                )

                for j in range(
                    buttons.count()
                ):

                    try:

                        btn = buttons.nth(j)

                        if not btn.is_visible():
                            continue

                        txt = (
                            btn.inner_text()
                            .strip()
                            .lower()
                        )

                        if txt in {
                            "ok",
                            "confirm",
                            "done",
                            "save",
                            "নিশ্চিত"
                        }:

                            print(
                                "✓ Confirming image crop...",
                                flush=True
                            )

                            btn.click(
                                force=True
                            )

                            page.wait_for_timeout(
                                2000
                            )

                            return

                    except Exception:
                        continue

    except Exception:
        pass


def wait_for_modal_close(
    page,
    seconds=5
):

    end = (
        time.time()
        + seconds
    )

    while time.time() < end:

        try:

            visible = page.locator(
                ".ant-modal-wrap:visible"
            ).count()

            if visible == 0:
                return True

        except Exception:

            return True

        page.wait_for_timeout(300)

    return False


# ============================================================
# FIRST PUBLISH
# ============================================================

def click_first_publish(page):

    print(
        "Attempting to click first Publish...",
        flush=True
    )

    for attempt in range(5):

        remove_overlays(page)

        close_crop_modal(page)

        page.wait_for_timeout(1000)

        btn = page.locator(
            'button:has-text("Publish"), '
            'button:has-text("প্রকাশ করুন"), '
            'button:has-text("পোস্ট করুন"), '
            '.ant-btn-primary:has-text("Publish")'
        ).first

        if (
            btn.count() > 0
            and btn.is_visible()
        ):

            try:

                btn.click(
                    force=True,
                    timeout=10000
                )

                print(
                    "✓ First Publish clicked.",
                    flush=True
                )

                page.wait_for_timeout(
                    4000
                )

                if (
                    page.locator(
                        ".ant-modal-wrap:visible, "
                        ".ant-modal:visible"
                    ).count() > 0
                ):
                    return True

            except Exception as e:

                print(
                    f"First publish click note: {e}",
                    flush=True
                )

        page.wait_for_timeout(2000)

    return (
        page.locator(
            ".ant-modal-wrap:visible, "
            ".ant-modal:visible"
        ).count() > 0
    )


# ============================================================
# CATEGORY
# ============================================================

def select_category_in_modal(page):

    print(
        "Waiting for Publish modal and "
        "Category selector to load...",
        flush=True
    )

    remove_overlays(page)

    modal = page.locator(
        ".ant-modal:visible, "
        ".ant-modal-wrap:visible, "
        "[role='dialog']:visible"
    ).last

    try:

        modal.wait_for(
            state="visible",
            timeout=15000
        )

    except Exception:
        pass

    cat_selectors = [
        '.ant-modal:visible .ant-select-selector',
        '.ant-modal-wrap:visible .ant-select-selector',
        '[role="dialog"] .ant-select-selector',
        '.ant-modal:visible .ant-select',
        '.ant-select-selector:visible'
    ]

    select_box = None

    for sel in cat_selectors:

        loc = page.locator(sel)

        try:

            loc.first.wait_for(
                state="visible",
                timeout=8000
            )

            select_box = loc.first
            break

        except Exception:
            continue

    if select_box:

        print(
            "✓ Category selector found. "
            "Opening dropdown...",
            flush=True
        )

        try:

            select_box.click(
                force=True
            )

            page.wait_for_timeout(
                1500
            )

            option = page.locator(
                '.ant-select-dropdown:not(.ant-select-dropdown-hidden) '
                '.ant-select-item-option, '
                '[role="option"]:visible, '
                '.ant-select-item-option-content:visible'
            ).first

            option.wait_for(
                state="visible",
                timeout=8000
            )

            cat_name = (
                option.inner_text()
                .strip()
            )

            option.click(
                force=True
            )

            print(
                f"✓ Category successfully selected: "
                f"{cat_name}",
                flush=True
            )

            page.wait_for_timeout(
                2500
            )

            return True

        except Exception as e:

            print(
                f"Dropdown option click note: {e}",
                flush=True
            )

    else:

        print(
            "⚠ Category selector could not "
            "be found with wait.",
            flush=True
        )

    return False


# ============================================================
# FINAL PUBLISH
# IMPORTANT: ONLY ONE CLICK
# ============================================================

def click_final_publish(page):

    print(
        "Searching for final Publish button...",
        flush=True
    )

    remove_overlays(page)

    page.wait_for_timeout(2000)

    modal = page.locator(
        ".ant-modal:visible, "
        ".ant-modal-wrap:visible"
    ).last

    if modal.count() == 0:

        print(
            "❌ Publish modal not found.",
            flush=True
        )

        return False

    buttons = modal.locator(
        'button.ant-btn-primary, '
        'button:has-text("Publish"), '
        'button:has-text("প্রকাশ করুন")'
    )

    if buttons.count() == 0:

        print(
            "❌ Final Publish button not found.",
            flush=True
        )

        return False

    # Try the last matching button
    btn = buttons.last

    try:

        btn.wait_for(
            state="visible",
            timeout=10000
        )

        page.wait_for_timeout(
            1500
        )

        # DO NOT JS CLICK + PLAYWRIGHT CLICK.
        # Only one real click.
        print(
            "Clicking final Publish button once...",
            flush=True
        )

        btn.click(
            force=True,
            timeout=10000
        )

        print(
            "✓ FINAL PUBLISH CLICKED SUCCESSFULLY.",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"Final click failed: {e}",
            flush=True
        )

        return False


# ============================================================
# DEBUG
# ============================================================

def save_debug(page):

    try:

        filename = (
            "serey_debug_"
            + str(int(time.time()))
            + ".html"
        )

        html = page.content()

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(html)

        print(
            f"✓ Debug HTML saved: {filename}",
            flush=True
        )

    except Exception as e:

        print(
            f"Debug save failed: {e}",
            flush=True
        )


# ============================================================
# CLEAN TEMP IMAGE
# ============================================================

def remove_temp_image(
    downloaded_img
):

    if (
        downloaded_img
        and os.path.exists(
            downloaded_img
        )
    ):

        try:

            os.remove(
                downloaded_img
            )

        except Exception:
            pass


# ============================================================
# PUBLISH
# ============================================================

def publish(page, post):

    print(
        "-" * 60,
        flush=True
    )

    print(
        f"Publishing: "
        f"{post['title']} "
        f"(Steem Date: "
        f"{post.get('created', 'N/A')})",
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

    remove_overlays(page)

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_box = page.locator(
        'input[placeholder*="title" i], '
        'textarea[placeholder*="title" i], '
        'input[placeholder*="Enter title" i]'
    ).first

    title_box.wait_for(
        state="visible",
        timeout=20000
    )

    title_box.fill(
        post["title"]
    )

    print(
        "✓ Title filled",
        flush=True
    )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    editor = page.locator(
        '.ql-editor, '
        'div[contenteditable="true"]'
    ).first

    editor.wait_for(
        state="visible",
        timeout=20000
    )

    try:

        editor.fill(
            post["body"]
        )

    except Exception:

        editor.click(
            force=True
        )

        page.keyboard.insert_text(
            post["body"]
        )

    print(
        f"✓ Body filled "
        f"({len(post['body'])} characters)",
        flush=True
    )

    page.wait_for_timeout(
        1500
    )

    # --------------------------------------------------------
    # THUMBNAIL
    # --------------------------------------------------------

    downloaded_img = download_image(
        post.get("thumbnail")
    )

    if downloaded_img:

        try:

            file_inputs = page.locator(
                'input[type="file"]'
            )

            if file_inputs.count() > 0:

                file_inputs.first.set_input_files(
                    downloaded_img
                )

                print(
                    "✓ Thumbnail uploaded.",
                    flush=True
                )

                page.wait_for_timeout(
                    7000
                )

                close_crop_modal(
                    page
                )

                wait_for_modal_close(
                    page,
                    seconds=5
                )

                print(
                    "✓ Thumbnail processing finished.",
                    flush=True
                )

        except Exception as e:

            print(
                f"❌ Thumbnail upload failed: {e}",
                flush=True
            )

    # --------------------------------------------------------
    # FIRST PUBLISH
    # --------------------------------------------------------

    if not click_first_publish(
        page
    ):

        print(
            "❌ Could not open Publish modal.",
            flush=True
        )

        save_debug(page)

        remove_temp_image(
            downloaded_img
        )

        return None

    print(
        "✓ Publish modal opened.",
        flush=True
    )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    select_category_in_modal(
        page
    )

    # --------------------------------------------------------
    # NETWORK CAPTURE
    # Attach BEFORE FINAL PUBLISH
    # --------------------------------------------------------

    capture = NetworkCapture()

    capture.attach(
        page
    )

    # --------------------------------------------------------
    # FINAL PUBLISH
    # --------------------------------------------------------

    if not click_final_publish(
        page
    ):

        print(
            "❌ Final Publish button "
            "could not be clicked.",
            flush=True
        )

        save_debug(page)

        remove_temp_image(
            downloaded_img
        )

        return None

    print(
        "Waiting for Serey publish response...",
        flush=True
    )

    # --------------------------------------------------------
    # PHASE 1:
    # WAIT FOR DIRECT URL
    # --------------------------------------------------------

    for i in range(
        PUBLISH_WAIT_SECONDS
    ):

        page.wait_for_timeout(
            1000
        )

        print(
            f"Waiting... "
            f"{i + 1}/{PUBLISH_WAIT_SECONDS} sec "
            f"| URL: {page.url}",
            flush=True
        )

        if is_real_post_url(
            page.url
        ):

            print(
                "✓ REAL POST URL detected immediately.",
                flush=True
            )

            candidate = page.url

            if verify_real_post_page(
                page,
                candidate,
                post["title"]
            ):

                remove_temp_image(
                    downloaded_img
                )

                return candidate

    # --------------------------------------------------------
    # PHASE 2:
    # NETWORK
    # --------------------------------------------------------

    api_urls = analyze_network_responses(
        capture,
        post["title"]
    )

    for candidate in api_urls:

        if verify_real_post_page(
            page,
            candidate,
            post["title"]
        ):

            remove_temp_image(
                downloaded_img
            )

            return candidate

    # --------------------------------------------------------
    # PHASE 3:
    # CURRENT PAGE LINKS
    # --------------------------------------------------------

    print(
        "Checking links on current Serey page...",
        flush=True
    )

    current_links = (
        find_real_post_links(page)
    )

    for candidate in current_links:

        if verify_real_post_page(
            page,
            candidate,
            post["title"]
        ):

            remove_temp_image(
                downloaded_img
            )

            return candidate

    # --------------------------------------------------------
    # PHASE 4:
    # ACTIVITY PAGE
    # --------------------------------------------------------

    activity_links = (
        search_activity_for_post(
            page,
            post["title"]
        )
    )

    for candidate in activity_links:

        if verify_real_post_page(
            page,
            candidate,
            post["title"]
        ):

            remove_temp_image(
                downloaded_img
            )

            return candidate

    # --------------------------------------------------------
    # FAILED
    # --------------------------------------------------------

    print(
        "\n" + "=" * 60,
        flush=True
    )

    print(
        "❌ PUBLISH COULD NOT BE VERIFIED",
        flush=True
    )

    print(
        f"Final browser URL: {page.url}",
        flush=True
    )

    print(
        "=" * 60,
        flush=True
    )

    save_debug(
        page
    )

    remove_temp_image(
        downloaded_img
    )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "STEEM -> BENGALI SEREY AUTO SYNC"
    )

    print(
        "LAST 365 DAYS -> OLDEST TO NEWEST"
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # ENV CHECK
    # --------------------------------------------------------

    if (
        not STEEM_USERNAME
        or not SEREY_LOGIN
        or not SEREY_PASSWORD
    ):

        print(
            "❌ Error: Missing Environment Secrets!",
            flush=True
        )

        return

    # --------------------------------------------------------
    # LOAD SYNCED
    # --------------------------------------------------------

    synced = load_synced()

    print(
        f"Previously synced: "
        f"{len(synced)}",
        flush=True
    )

    # --------------------------------------------------------
    # GET POSTS
    # --------------------------------------------------------

    posts = get_posts()

    new_posts = [
        p
        for p in posts
        if p["id"] not in synced
    ]

    print(
        f"Unsynced posts remaining "
        f"(Last 1 Year): "
        f"{len(new_posts)}",
        flush=True
    )

    posts_to_run = (
        new_posts[:POSTS_PER_RUN]
    )

    if not posts_to_run:

        print(
            "No new posts to publish.",
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

    # --------------------------------------------------------
    # PLAYWRIGHT
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage"
            ]
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

                    published_url = publish(
                        page,
                        post
                    )

                    if (
                        published_url
                        and is_real_post_url(
                            published_url
                        )
                    ):

                        print(
                            "\n✓✓✓ "
                            "PUBLISHED SUCCESSFULLY "
                            "✓✓✓",
                            flush=True
                        )

                        print(
                            f"Published URL: "
                            f"{published_url}",
                            flush=True
                        )

                        # ONLY NOW mark as synced
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
                            f"\n⚠ FAILED: "
                            f"{post['id']}",
                            flush=True
                        )

                        print(
                            "⚠ This post will NOT "
                            "be added to synced_posts.json.",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publish error: {e}",
                        flush=True
                    )

                    print(
                        f"⚠ FAILED: {post['id']}",
                        flush=True
                    )

        finally:

            browser.close()

    print(
        "\n" + "=" * 60
    )

    print(
        "RUN FINISHED"
    )

    print(
        "=" * 60
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
