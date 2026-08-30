import os, json, re, time, requests
from playwright.sync_api import sync_playwright

# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]
SEREY_LOGIN = os.environ.get("SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")).replace("@", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io",
    "https://api.steem-fanbase.com",
    "https://api.steem.buzz",
    "https://steemd.privex.io",
    "https://api.steemitdev.com"
]

SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

DATA_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_thumbnail.jpg"

POSTS_PER_RUN = 1
CATEGORY = "Society"

DEAD_DOMAINS = ["img.esteem.ws", "esteem.ws"]


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

    last = None

    for node in STEEM_NODES:
        try:
            print(f"RPC: {node}", flush=True)

            r = requests.post(
                node,
                json=payload,
                timeout=20
            )
            r.raise_for_status()

            data = r.json()

            if "error" in data:
                raise RuntimeError(data["error"])

            return data["result"]

        except Exception as e:
            last = e
            print(f"RPC failed: {e}", flush=True)

    raise RuntimeError(f"All Steem RPC nodes failed: {last}")


# ============================================================
# SYNC FILE
# ============================================================

def load_synced():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def save_synced(posts):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(posts),
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# IMAGE + BODY
# ============================================================

def dead(url):
    return not url or any(x in url.lower() for x in DEAD_DOMAINS)


def clean_post(body, metadata):

    image = None

    try:
        meta = json.loads(metadata)

        for img in meta.get("image", []):
            if not dead(img):
                image = img
                break

    except Exception:
        pass

    if not image:
        patterns = [
            r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
            r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?'
        ]

        for pattern in patterns:
            found = re.findall(pattern, body, re.I)

            for img in found:
                if not dead(img):
                    image = img
                    break

            if image:
                break

    body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    body = re.sub(
        r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
        '',
        body,
        flags=re.I
    )

    body = re.sub(
        r'\n\s*\n\s*\n+',
        '\n\n',
        body
    )

    return image, body.strip()


# ============================================================
# FETCH STEEM POSTS
# ============================================================

def get_posts():

    print(
        f"\nFetching posts from @{STEEM_USERNAME}...",
        flush=True
    )

    posts = []
    seen = set()

    start_author = None
    start_permlink = None
    page = 0

    while len(posts) < 5000:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }

        if start_author and start_permlink:
            params.update({
                "start_author": start_author,
                "start_permlink": start_permlink
            })

        page += 1

        try:
            result = rpc(
                "condenser_api.get_discussions_by_blog",
                params
            )
        except Exception as e:
            print(f"Fetch failed: {e}", flush=True)
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

        for p in batch:

            if p.get("author") != STEEM_USERNAME:
                continue

            author = p.get("author", "")
            permlink = p.get("permlink", "")
            post_id = f"{author}/{permlink}"

            if not permlink or post_id in seen:
                continue

            seen.add(post_id)

            image, body = clean_post(
                p.get("body", ""),
                p.get("json_metadata", "{}")
            )

            posts.append({
                "author": author,
                "permlink": permlink,
                "title": p.get("title", ""),
                "body": body,
                "image": image,
                "category": p.get("category", ""),
                "created": p.get("created", "")
            })

            added += 1

            if len(posts) >= 5000:
                break

        print(
            f"Batch {page}: {len(result)} received | "
            f"Total: {len(posts)}",
            flush=True
        )

        last = result[-1]
        new_author = last.get("author")
        new_permlink = last.get("permlink")

        if (
            new_author == start_author
            and new_permlink == start_permlink
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

    print(
        f"Total historical posts fetched: {len(posts)}",
        flush=True
    )

    return posts


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    if dead(url):
        return None

    try:
        print(f"Downloading image: {url}", flush=True)

        r = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        r.raise_for_status()

        if "image" not in r.headers.get(
            "content-type", ""
        ).lower():
            return None

        with open(TEMP_IMAGE, "wb") as f:
            f.write(r.content)

        print("Image downloaded successfully!", flush=True)

        return TEMP_IMAGE

    except Exception as e:
        print(f"Image download failed: {e}", flush=True)
        return None


# ============================================================
# SEREY CATEGORY
# ============================================================

def click_text(page, text):

    selectors = [
        f'text="{text}"',
        f'[role="option"]:has-text("{text}")',
        f'.ant-select-item-option:has-text("{text}")',
        f'button:has-text("{text}")',
        f'div:has-text("{text}")',
        f'span:has-text("{text}")'
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector)

            for i in range(min(loc.count(), 10)):
                item = loc.nth(i)

                if item.is_visible(timeout=300):
                    item.click(
                        force=True,
                        timeout=5000
                    )
                    return True

        except Exception:
            pass

    return False


def select_category(page):

    print("Selecting category...", flush=True)

    selectors = [
        'text="Select category"',
        'div:has-text("Select category")',
        'span:has-text("Select category")',
        '[role="combobox"]'
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector)

            for i in range(min(loc.count(), 10)):
                item = loc.nth(i)

                if item.is_visible(timeout=300):
                    item.click(
                        force=True,
                        timeout=5000
                    )

                    page.wait_for_timeout(800)

                    if click_text(page, CATEGORY):
                        print(
                            f"Category selected: {CATEGORY}",
                            flush=True
                        )
                        return True

        except Exception:
            pass

    print("Category selection failed.", flush=True)
    return False


# ============================================================
# SUB CATEGORY
# ============================================================

def select_subcategory(page):

    print("Selecting sub category...", flush=True)

    selectors = [
        'text="Select sub category"',
        'div:has-text("Select sub category")',
        'span:has-text("Select sub category")'
    ]

    control = None

    for selector in selectors:
        try:
            loc = page.locator(selector)

            for i in range(min(loc.count(), 10)):
                item = loc.nth(i)

                if item.is_visible(timeout=300):
                    control = item
                    break

            if control:
                break

        except Exception:
            pass

    if not control:
        print("Sub category control not found.", flush=True)
        return False

    try:
        control.click(
            force=True,
            timeout=5000
        )

        page.wait_for_timeout(800)

    except Exception:
        return False

    # Select first available visible option
    for selector in [
        '[role="option"]',
        '.ant-select-item-option',
        '.dropdown-item',
        'li'
    ]:

        try:
            loc = page.locator(selector)

            for i in range(min(loc.count(), 50)):
                item = loc.nth(i)

                if not item.is_visible(timeout=300):
                    continue

                text = item.inner_text(
                    timeout=300
                ).strip()

                if not text:
                    continue

                if text.lower() in [
                    "select sub category",
                    "sub category"
                ]:
                    continue

                item.click(
                    force=True,
                    timeout=5000
                )

                print(
                    f"Sub category selected: {text}",
                    flush=True
                )

                return True

        except Exception:
            pass

    print("Sub category selection failed.", flush=True)
    return False


# ============================================================
# FINAL PUBLISH
# ============================================================

def final_publish(page):

    print(
        "Looking for Final Publish...",
        flush=True
    )

    selectors = [
        'button:has-text("Publish")',
        'button:has-text("Post to Blockchain")',
        '[role="button"]:has-text("Publish")'
    ]

    for selector in selectors:

        try:
            loc = page.locator(selector)

            for i in range(min(loc.count(), 20)):
                btn = loc.nth(i)

                if not btn.is_visible(timeout=300):
                    continue

                text = btn.inner_text(
                    timeout=300
                ).strip().lower()

                if (
                    "publish" in text
                    or
                    "post to blockchain" in text
                ):

                    btn.click(
                        force=True,
                        timeout=5000
                    )

                    print(
                        "Final Publish clicked!",
                        flush=True
                    )

                    return True

        except Exception:
            pass

    print(
        "Final Publish button not found.",
        flush=True
    )

    return False


# ============================================================
# VERIFY
# ============================================================

def normalize(text):
    text = text.lower()
    text = re.sub(
        r'[^a-z0-9\u0980-\u09ff\s]',
        ' ',
        text
    )
    return re.sub(r'\s+', ' ', text).strip()


def verify(page, post):

    title = normalize(post["title"])

    print(
        f"Verifying: {post['title']}",
        flush=True
    )

    page.wait_for_timeout(5000)

    # Direct published URL
    if (
        "blog/post/new" not in page.url
        and
        (
            "/authors/" in page.url
            or
            "/blog/post/" in page.url
        )
    ):

        try:
            if title in normalize(page.content()):
                print(
                    f"POST VERIFIED: {page.url}",
                    flush=True
                )
                return True
        except Exception:
            pass

    # Author profile
    for url in [
        f"{SEREY}/authors/{SEREY_LOGIN}",
        f"{SEREY}/authors/@{SEREY_LOGIN}"
    ]:

        try:

            page.goto(
                url,
                timeout=30000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(4000)

            if title in normalize(page.content()):

                print(
                    f"POST FOUND ON PROFILE: {url}",
                    flush=True
                )

                return True

        except Exception as e:
            print(
                f"Verification error: {e}",
                flush=True
            )

    return False


# ============================================================
# PUBLISH ONE POST
# ============================================================

def publish(page, post):

    print(
        f"\n---> Publishing: {post['title']}",
        flush=True
    )

    try:

        page.goto(
            NEW_POST,
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(3000)

        # Title
        page.locator(
            'input[placeholder*="title" i]'
        ).first.fill(
            post["title"]
        )

        print("Title filled!", flush=True)

        # Content
        page.locator(
            'div[contenteditable="true"], textarea'
        ).first.fill(
            post["body"]
        )

        print("Content filled!", flush=True)

        # Thumbnail
        if post.get("image"):

            img = download_image(
                post["image"]
            )

            if img:

                try:

                    file_input = page.locator(
                        'input[type="file"]'
                    ).first

                    if file_input.count():

                        file_input.set_input_files(img)

                        print(
                            "Thumbnail uploaded!",
                            flush=True
                        )

                        page.wait_for_timeout(2500)

                except Exception as e:
                    print(
                        f"Thumbnail skipped: {e}",
                        flush=True
                    )

        # First Publish
        publish_btn = page.locator(
            'button:has-text("Publish")'
        ).first

        publish_btn.click(
            force=True,
            timeout=10000
        )

        print(
            "First Publish clicked!",
            flush=True
        )

        page.wait_for_timeout(2500)

        # Category
        select_category(page)

        page.wait_for_timeout(1000)

        # Sub Category
        select_subcategory(page)

        page.wait_for_timeout(1000)

        # Final Publish
        if not final_publish(page):
            raise RuntimeError(
                "Final Publish button not found."
            )

        page.wait_for_timeout(15000)

        print(
            f"After publish URL: {page.url}",
            flush=True
        )

        # Verify
        if verify(page, post):

            print(
                "VERIFIED & CONFIRMED!",
                flush=True
            )

            return True

        print(
            "Publish could not be verified.",
            flush=True
        )

        return False

    except Exception as e:

        print(
            f"Publish failed: {e}",
            flush=True
        )

        return False

    finally:

        if os.path.exists(TEMP_IMAGE):

            try:
                os.remove(TEMP_IMAGE)
            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("STEEMIT -> SEREY BENGALI SYNC")
    print("=" * 60)

    synced = load_synced()

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    posts = get_posts()

    new_posts = [
        p for p in posts
        if f'{p["author"]}/{p["permlink"]}' not in synced
    ]

    print(
        f"Total posts: {len(posts)}",
        flush=True
    )

    print(
        f"Unsynced posts: {len(new_posts)}",
        flush=True
    )

    posts_to_run = new_posts[:POSTS_PER_RUN]

    print(
        f"Publishing this run: {len(posts_to_run)}",
        flush=True
    )

    if not posts_to_run:
        print("Nothing to sync.")
        return

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

        # Login
        try:

            print(
                "Logging into Serey...",
                flush=True
            )

            page.goto(
                SEREY,
                timeout=60000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(3000)

            page.locator(
                'a:has-text("Log in"), '
                'button:has-text("Log in"), '
                'a:has-text("Log In"), '
                'button:has-text("Log In")'
            ).first.click(
                force=True
            )

            page.wait_for_timeout(3000)

            page.locator(
                'input[placeholder*="Username"]'
            ).first.fill(
                SEREY_LOGIN
            )

            page.locator(
                'input[placeholder*="Private Key"]'
            ).first.fill(
                SEREY_PASSWORD
            )

            page.locator(
                'button:has-text("Log in"), '
                'button:has-text("Log In")'
            ).last.click(
                force=True
            )

            page.wait_for_timeout(6000)

            print(
                "LOGGED INTO SEREY SUCCESSFULLY!",
                flush=True
            )

        except Exception as e:

            print(
                f"Login failed: {e}",
                flush=True
            )

            browser.close()
            return

        # Publish
        for post in posts_to_run:

            if publish(page, post):

                post_id = (
                    f'{post["author"]}/'
                    f'{post["permlink"]}'
                )

                synced.add(post_id)

                save_synced(synced)

                print(
                    f"Saved as synced: {post_id}",
                    flush=True
                )

            else:

                print(
                    "Post NOT verified. "
                    "It will retry next run.",
                    flush=True
                )

        browser.close()

    print("=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
