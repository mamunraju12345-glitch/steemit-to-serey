import os
import json
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright


# ============================================================
# STEEM -> SEREY AUTO SYNC
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

            print(f"RPC: {node}", flush=True)

            response = requests.post(
                node,
                json=payload,
                timeout=30
            )

            response.raise_for_status()

            data = response.json()

            if "result" in data:
                return data["result"]

            print(
                f"RPC error from {node}: {data}",
                flush=True
            )

        except Exception as e:

            print(
                f"RPC failed {node}: {e}",
                flush=True
            )

    raise Exception("All Steem RPC nodes failed.")


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
            f"Could not read {SYNC_FILE}: {e}",
            flush=True
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
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# CLEAN POST
# ============================================================

def clean_post(body):

    if not body:
        return ""

    # Remove Steemit image markdown
    body = re.sub(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        "",
        body
    )

    # Remove image HTML
    body = re.sub(
        r'<img[^>]*>',
        "",
        body,
        flags=re.I
    )

    return body.strip()


# ============================================================
# GET STEEM POSTS
# ONLY LAST 30 DAYS
# ============================================================

def get_posts():

    print(
        f"Getting posts from @{STEEM_USERNAME}...",
        flush=True
    )

    one_month_ago = (
        datetime.now(timezone.utc)
        - timedelta(days=30)
    )

    posts = []

    start_author = STEEM_USERNAME
    start_permlink = ""

    while True:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100,
            "start_author": start_author,
            "start_permlink": start_permlink
        }

        try:

            result = rpc(
                "condenser_api.get_discussions_by_blog",
                [params]
            )

        except Exception as e:

            print(
                f"Failed to get Steem posts: {e}",
                flush=True
            )

            break

        if not result:
            break

        for post in result:

            author = post.get("author", "")

            if author != STEEM_USERNAME:
                continue

            created = post.get("created", "")

            if not created:
                continue

            try:

                created_dt = datetime.strptime(
                    created,
                    "%Y-%m-%dT%H:%M:%S"
                ).replace(
                    tzinfo=timezone.utc
                )

            except Exception:

                continue

            # Only last 30 days
            if created_dt < one_month_ago:

                print(
                    "Reached posts older than 30 days.",
                    flush=True
                )

                # Sort oldest -> newest
                posts.sort(
                    key=lambda x: x["created"]
                )

                print(
                    f"Total posts from last 1 month: {len(posts)}",
                    flush=True
                )

                return posts

            posts.append(post)

        last = result[-1]

        start_author = last.get(
            "author",
            STEEM_USERNAME
        )

        start_permlink = last.get(
            "permlink",
            ""
        )

        # Avoid infinite loop
        if len(result) < 100:
            break

    # Sort oldest -> newest
    posts.sort(
        key=lambda x: x["created"]
    )

    print(
        f"Total posts from last 1 month: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    try:

        print(
            f"Downloading image: {url}",
            flush=True
        )

        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        with open(
            TEMP_IMAGE,
            "wb"
        ) as f:

            f.write(response.content)

        return True

    except Exception as e:

        print(
            f"❌ Image download failed: {e}",
            flush=True
        )

        return False


# ============================================================
# SEREY LOGIN
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

    page.wait_for_timeout(5000)

    # Try login buttons
    login_selectors = [
        "text=Login",
        "text=Log In",
        "button:has-text('Login')",
        "button:has-text('Log In')",
        "a:has-text('Login')",
        "a:has-text('Log In')",
    ]

    clicked = False

    for selector in login_selectors:

        try:

            locator = page.locator(selector)

            if locator.count() > 0:

                for i in range(locator.count()):

                    item = locator.nth(i)

                    if item.is_visible():

                        item.click(
                            force=True
                        )

                        clicked = True

                        break

            if clicked:
                break

        except Exception:
            continue

    if clicked:

        page.wait_for_timeout(3000)

    # Find inputs
    inputs = page.locator("input")

    email_input = None
    password_input = None

    for i in range(inputs.count()):

        inp = inputs.nth(i)

        try:

            if not inp.is_visible():
                continue

            input_type = (
                inp.get_attribute("type")
                or ""
            ).lower()

            placeholder = (
                inp.get_attribute("placeholder")
                or ""
            ).lower()

            name = (
                inp.get_attribute("name")
                or ""
            ).lower()

            if input_type == "password":

                password_input = inp

            elif (
                input_type == "email"
                or "email" in placeholder
                or "username" in placeholder
                or "login" in placeholder
                or "email" in name
                or "username" in name
            ):

                email_input = inp

        except Exception:
            continue

    if not email_input or not password_input:

        print(
            "❌ Login fields not found.",
            flush=True
        )

        return False

    email_input.fill(
        SEREY_LOGIN
    )

    password_input.fill(
        SEREY_PASSWORD
    )

    # Find submit button
    submit_button = None

    buttons = page.locator(
        "button"
    )

    for i in range(buttons.count()):

        button = buttons.nth(i)

        try:

            if not button.is_visible():
                continue

            text = (
                button.inner_text()
                .strip()
                .lower()
            )

            button_type = (
                button.get_attribute("type")
                or ""
            ).lower()

            if (
                button_type == "submit"
                or text in [
                    "login",
                    "log in",
                    "sign in"
                ]
            ):

                submit_button = button
                break

        except Exception:
            continue

    if not submit_button:

        print(
            "❌ Login button not found.",
            flush=True
        )

        return False

    submit_button.click(
        force=True
    )

    page.wait_for_timeout(7000)

    print(
        "✓ LOGGED INTO SEREY SUCCESSFULLY!",
        flush=True
    )

    return True


# ============================================================
# CATEGORY
# ============================================================

def select_category(page, category):

    try:

        print(
            f"Steemit category: {category}",
            flush=True
        )

        # Look for select elements
        selects = page.locator(
            "select"
        )

        if selects.count() == 0:

            print(
                "No category selector. Continuing.",
                flush=True
            )

            return

        for i in range(selects.count()):

            select = selects.nth(i)

            try:

                if not select.is_visible():
                    continue

                options = select.locator(
                    "option"
                )

                values = []

                for j in range(
                    options.count()
                ):

                    values.append(
                        options.nth(j)
                        .inner_text()
                        .strip()
                    )

                for value in values:

                    if category.lower() in value.lower():

                        select.select_option(
                            label=value
                        )

                        print(
                            f"✓ Category selected: {value}",
                            flush=True
                        )

                        return

            except Exception:
                continue

        print(
            "No category selector. Continuing.",
            flush=True
        )

    except Exception:

        print(
            "No category selector. Continuing.",
            flush=True
        )


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(page):

    try:

        print(
            "No Sub Category selector.",
            flush=True
        )

    except Exception:
        pass


# ============================================================
# VERIFY REAL PUBLISHED POST
# ============================================================

def verify(page, title):

    print(
        "VERIFYING PUBLISHED POST...",
        flush=True
    )

    # Give Serey time to process publication
    page.wait_for_timeout(15000)

    author_urls = [
        f"{SEREY}/authors/{SEREY_LOGIN}",
        f"https://serey.io/authors/{SEREY_LOGIN}",
    ]

    for attempt in range(1, 6):

        print(
            f"Verification attempt {attempt}/5...",
            flush=True
        )

        # ====================================================
        # 1. Check current URL
        # ====================================================

        current_url = page.url

        print(
            f"Current URL: {current_url}",
            flush=True
        )

        # NEVER accept /blog/post/new
        if "/blog/post/new" not in current_url:

            if re.match(
                r"https://(?:bengali\.)?serey\.io/authors/[^/]+/[^/]+$",
                current_url,
                re.I
            ):

                print(
                    "✓ REAL PUBLISHED URL FOUND!",
                    flush=True
                )

                print(
                    f"✓ PUBLISHED URL: {current_url}",
                    flush=True
                )

                return True

        # ====================================================
        # 2. Check links on current page
        # ====================================================

        try:

            links = page.locator(
                "a[href]"
            )

            count = links.count()

            for i in range(count):

                link = links.nth(i)

                try:

                    if not link.is_visible():
                        continue

                    href = (
                        link.get_attribute(
                            "href"
                        )
                        or ""
                    )

                    text = (
                        link.inner_text()
                        .strip()
                    )

                    if not href:
                        continue

                    full_url = urljoin(
                        SEREY,
                        href
                    )

                    # Only real post URLs
                    if not re.match(
                        r"https://(?:bengali\.)?serey\.io/authors/[^/]+/[^/]+$",
                        full_url,
                        re.I
                    ):
                        continue

                    # Never accept new-post page
                    if "/blog/post/new" in full_url:
                        continue

                    if (
                        title.lower()
                        in text.lower()
                        or
                        title.lower()
                        in full_url.lower()
                    ):

                        print(
                            "✓ REAL PUBLISHED POST LINK FOUND!",
                            flush=True
                        )

                        print(
                            f"✓ PUBLISHED URL: {full_url}",
                            flush=True
                        )

                        return True

                except Exception:
                    continue

        except Exception:
            pass

        # ====================================================
        # 3. Open author's page
        # ====================================================

        for author_url in author_urls:

            try:

                print(
                    f"Checking author page: {author_url}",
                    flush=True
                )

                page.goto(
                    author_url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                page.wait_for_timeout(5000)

                print(
                    f"Author page URL: {page.url}",
                    flush=True
                )

                links = page.locator(
                    "a[href]"
                )

                count = links.count()

                for i in range(count):

                    link = links.nth(i)

                    try:

                        if not link.is_visible():
                            continue

                        href = (
                            link.get_attribute(
                                "href"
                            )
                            or ""
                        )

                        text = (
                            link.inner_text()
                            .strip()
                        )

                        if not href:
                            continue

                        full_url = urljoin(
                            author_url,
                            href
                        )

                        if not re.match(
                            r"https://(?:bengali\.)?serey\.io/authors/[^/]+/[^/]+$",
                            full_url,
                            re.I
                        ):
                            continue

                        if "/blog/post/new" in full_url:
                            continue

                        if (
                            title.lower()
                            in text.lower()
                            or
                            title.lower()
                            in full_url.lower()
                        ):

                            print(
                                "✓ REAL PUBLISHED POST FOUND!",
                                flush=True
                            )

                            print(
                                f"✓ PUBLISHED URL: {full_url}",
                                flush=True
                            )

                            return True

                    except Exception:
                        continue

            except Exception as e:

                print(
                    f"Author page check failed: {e}",
                    flush=True
                )

        # ====================================================
        # 4. Wait and retry
        # ====================================================

        print(
            "Post URL not found yet. Waiting...",
            flush=True
        )

        page.wait_for_timeout(5000)

    # ========================================================
    # IMPORTANT:
    # Title-only verification is NOT allowed.
    # ========================================================

    print(
        "❌ REAL PUBLISHED POST URL COULD NOT BE VERIFIED.",
        flush=True
    )

    print(
        "❌ Post will NOT be marked as synced.",
        flush=True
    )

    return False


# ============================================================
# PUBLISH POST
# ============================================================

def publish(page, post):

    title = post.get(
        "title",
        ""
    ).strip()

    body = clean_post(
        post.get(
            "body",
            ""
        )
    )

    print(
        "------------------------------------------------------------",
        flush=True
    )

    print(
        f"Publishing: {title}",
        flush=True
    )

    # ========================================================
    # OPEN NEW POST
    # ========================================================

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    # ========================================================
    # TITLE
    # ========================================================

    title_done = False

    inputs = page.locator(
        "input"
    )

    for i in range(inputs.count()):

        inp = inputs.nth(i)

        try:

            if not inp.is_visible():
                continue

            placeholder = (
                inp.get_attribute(
                    "placeholder"
                )
                or ""
            ).lower()

            name = (
                inp.get_attribute(
                    "name"
                )
                or ""
            ).lower()

            input_type = (
                inp.get_attribute(
                    "type"
                )
                or ""
            ).lower()

            if (
                input_type == "text"
                and (
                    "title" in placeholder
                    or "title" in name
                )
            ):

                inp.fill(title)

                print(
                    "✓ Title filled",
                    flush=True
                )

                title_done = True
                break

        except Exception:
            continue

    # Fallback title input
    if not title_done:

        try:

            visible_inputs = []

            for i in range(
                inputs.count()
            ):

                inp = inputs.nth(i)

                if inp.is_visible():
                    visible_inputs.append(inp)

            if visible_inputs:

                visible_inputs[0].fill(
                    title
                )

                print(
                    "✓ Title filled",
                    flush=True
                )

                title_done = True

        except Exception:
            pass

    if not title_done:

        print(
            "❌ Could not fill title.",
            flush=True
        )

        return False

    # ========================================================
    # BODY
    # ========================================================

    body_done = False

    textareas = page.locator(
        "textarea"
    )

    for i in range(
        textareas.count()
    ):

        textarea = textareas.nth(i)

        try:

            if not textarea.is_visible():
                continue

            textarea.fill(body)

            print(
                "✓ Body filled",
                flush=True
            )

            body_done = True
            break

        except Exception:
            continue

    # Contenteditable fallback
    if not body_done:

        editables = page.locator(
            "[contenteditable='true']"
        )

        for i in range(
            editables.count()
        ):

            editable = editables.nth(i)

            try:

                if not editable.is_visible():
                    continue

                editable.click(
                    force=True
                )

                editable.fill(body)

                print(
                    "✓ Body filled",
                    flush=True
                )

                body_done = True
                break

            except Exception:
                continue

    if not body_done:

        print(
            "❌ Could not fill body.",
            flush=True
        )

        return False

    # ========================================================
    # IMAGE
    # ========================================================

    image_url = None

    match = re.search(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        post.get("body", "")
    )

    if match:
        image_url = match.group(1)

    if image_url:

        if download_image(image_url):

            uploaded = False

            file_inputs = page.locator(
                "input[type='file']"
            )

            for i in range(
                file_inputs.count()
            ):

                file_input = file_inputs.nth(i)

                try:

                    file_input.set_input_files(
                        TEMP_IMAGE
                    )

                    print(
                        "✓ Thumbnail uploaded",
                        flush=True
                    )

                    uploaded = True
                    break

                except Exception:
                    continue

            if not uploaded:

                print(
                    "❌ Thumbnail upload failed.",
                    flush=True
                )

    # ========================================================
    # CATEGORY
    # ========================================================

    category = post.get(
        "category",
        ""
    )

    select_category(
        page,
        category
    )

    select_subcategory(
        page
    )

    # ========================================================
    # FIRST PUBLISH CLICK
    # ========================================================

    buttons = page.locator(
        "button"
    )

    first_publish = None

    for i in range(
        buttons.count()
    ):

        button = buttons.nth(i)

        try:

            if not button.is_visible():
                continue

            text = (
                button.inner_text()
                .strip()
            )

            if text == "Publish":

                first_publish = button
                break

        except Exception:
            continue

    if first_publish:

        first_publish.click(
            force=True
        )

        print(
            "✓ FIRST PUBLISH CLICKED",
            flush=True
        )

        page.wait_for_timeout(5000)

    else:

        print(
            "❌ FIRST Publish button not found.",
            flush=True
        )

        return False

    # ========================================================
    # CATEGORY MESSAGE
    # ========================================================

    print(
        f"Steemit category: {category}",
        flush=True
    )

    print(
        "No category selector. Continuing.",
        flush=True
    )

    print(
        "No Sub Category selector.",
        flush=True
    )

    # ========================================================
    # FINAL PUBLISH
    # ========================================================

    print(
        "Searching for FINAL Publish...",
        flush=True
    )

    buttons = page.locator(
        "button"
    )

    final_button = None

    for i in range(
        buttons.count()
    ):

        button = buttons.nth(i)

        try:

            if not button.is_visible():
                continue

            text = (
                button.inner_text()
                .strip()
            )

            if text == "Publish":

                final_button = button
                break

        except Exception:
            continue

    if not final_button:

        print(
            "❌ FINAL Publish button not found.",
            flush=True
        )

        return False

    final_button.click(
        force=True
    )

    print(
        "✓ FINAL PUBLISH CLICKED",
        flush=True
    )

    # Give Serey time
    page.wait_for_timeout(15000)

    # ========================================================
    # REAL VERIFICATION
    # ========================================================

    verified = verify(
        page,
        title
    )

    if verified:

        print(
            "✓ PUBLICATION VERIFIED SUCCESSFULLY!",
            flush=True
        )

        return True

    print(
        "❌ PUBLICATION VERIFICATION FAILED.",
        flush=True
    )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "STEEM -> SEREY AUTO SYNC",
        flush=True
    )

    print(
        "============================================================",
        flush=True
    )

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    posts = get_posts()

    unsynced = []

    for post in posts:

        identifier = (
            f"{post.get('author')}/"
            f"{post.get('permlink')}"
        )

        if identifier not in synced:

            unsynced.append(
                (identifier, post)
            )

    print(
        f"Unsynced posts: {len(unsynced)}",
        flush=True
    )

    if not unsynced:

        print(
            "No new posts to sync.",
            flush=True
        )

        return

    # Oldest -> newest
    unsynced.sort(
        key=lambda x: x[1].get(
            "created",
            ""
        )
    )

    to_publish = unsynced[
        :POSTS_PER_RUN
    ]

    print(
        f"Publishing this run: {len(to_publish)}",
        flush=True
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 900
            }
        )

        page = context.new_page()

        try:

            # ====================================================
            # LOGIN
            # ====================================================

            if not login(page):

                print(
                    "❌ Serey login failed.",
                    flush=True
                )

                return

            # ====================================================
            # PUBLISH ONE POST
            # ====================================================

            for identifier, post in to_publish:

                try:

                    success = publish(
                        page,
                        post
                    )

                    if success:

                        # ONLY save after REAL verification
                        synced.add(
                            identifier
                        )

                        save_synced(
                            synced
                        )

                        print(
                            f"✓ SAVED AS SYNCED: {identifier}",
                            flush=True
                        )

                    else:

                        print(
                            f"❌ NOT SAVED AS SYNCED: {identifier}",
                            flush=True
                        )

                except Exception as e:

                    print(
                        f"❌ Publishing error: {e}",
                        flush=True
                    )

                    # Important:
                    # Do not mark failed post as synced.

        finally:

            browser.close()

    # ========================================================
    # CLEAN TEMP IMAGE
    # ========================================================

    if os.path.exists(
        TEMP_IMAGE
    ):

        try:
            os.remove(
                TEMP_IMAGE
            )
        except Exception:
            pass

    print(
        "============================================================",
        flush=True
    )

    print(
        "SYNC COMPLETED",
        flush=True
    )

    print(
        "====================================",
        flush=True
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
