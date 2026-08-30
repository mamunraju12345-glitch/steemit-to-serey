import os
import json
import re
import requests
from playwright.sync_api import sync_playwright

USER = os.environ["STEEM_USERNAME"].strip()
LOGIN = os.environ.get("SEREY_LOGIN", "").replace("@", "").strip()
PASSWORD = os.environ["SEREY_PASSWORD"].strip()

SEREY = "https://bengali.serey.io"
NEW_POST = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
MAX_POSTS = 1000
POSTS_PER_RUN = 1

NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io"
]


def rpc(method, params):
    for node in NODES:
        try:
            print(f"RPC: {node}", flush=True)

            r = requests.post(
                node,
                json={
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": 1
                },
                timeout=20
            )

            data = r.json()

            if "result" in data:
                return data["result"]

        except Exception as e:
            print(f"RPC failed: {e}", flush=True)

    raise Exception("All Steem RPC nodes failed")


def load_synced():
    try:
        with open(SYNC_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()


def save_synced(data):
    with open(SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(data),
            f,
            ensure_ascii=False,
            indent=2
        )


def clean_body(body):
    return re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    ).strip()


def get_last_1000_posts():
    print(f"Getting last {MAX_POSTS} posts...", flush=True)

    posts = []
    seen = set()
    start_author = None
    start_permlink = None

    while len(posts) < MAX_POSTS:

        params = {
            "tag": USER,
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

        for post in result:

            if post.get("author") != USER:
                continue

            permlink = post.get("permlink", "")

            if not permlink:
                continue

            post_id = f"{USER}/{permlink}"

            if post_id in seen:
                continue

            seen.add(post_id)

            image = None

            try:
                metadata = json.loads(
                    post.get("json_metadata", "{}")
                )

                images = metadata.get("image", [])

                if images:
                    image = images[0]

            except:
                pass

            if not image:
                match = re.search(
                    r'!\[[^\]]*\]\((https?://[^)]+)',
                    post.get("body", "")
                )

                if match:
                    image = match.group(1)

            posts.append({
                "id": post_id,
                "title": post.get("title", "").strip(),
                "body": clean_body(
                    post.get("body", "")
                ),
                "image": image,
                "category": post.get("category", "")
            })

            if len(posts) >= MAX_POSTS:
                break

        last = result[-1]

        new_author = last.get("author")
        new_permlink = last.get("permlink")

        if (
            new_author == start_author
            and new_permlink == start_permlink
        ):
            break

        start_author = new_author
        start_permlink = new_permlink

        if len(result) < 100:
            break

    # OLD → NEW
    posts.reverse()

    print(
        f"Last {len(posts)} posts loaded.",
        flush=True
    )

    return posts


def login(page):
    print("Logging into Serey...", flush=True)

    page.goto(
        SEREY,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    page.locator(
        'a:has-text("Log in"),'
        'button:has-text("Log in"),'
        'a:has-text("Log In"),'
        'button:has-text("Log In")'
    ).first.click(force=True)

    page.wait_for_timeout(2000)

    page.locator(
        'input[placeholder*="Username"]'
    ).first.fill(LOGIN)

    page.locator(
        'input[placeholder*="Private Key"]'
    ).first.fill(PASSWORD)

    page.locator(
        'button:has-text("Log in"),'
        'button:has-text("Log In")'
    ).last.click(force=True)

    page.wait_for_timeout(5000)

    print("✓ SEREY LOGIN OK", flush=True)


def download_image(url):
    if not url:
        return None

    try:
        r = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        r.raise_for_status()

        if "image" not in r.headers.get(
            "content-type",
            ""
        ).lower():
            return None

        with open("temp.jpg", "wb") as f:
            f.write(r.content)

        return "temp.jpg"

    except Exception as e:
        print(
            f"Image failed: {e}",
            flush=True
        )
        return None


def publish(page, post):

    print("-" * 50)
    print(
        f"Publishing: {post['title']}",
        flush=True
    )

    page.goto(
        NEW_POST,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(2500)

    # TITLE
    page.locator(
        'input[placeholder*="Title" i]'
    ).first.fill(post["title"])

    print("✓ Title", flush=True)

    # BODY
    editor = page.locator(
        '[contenteditable="true"]'
    ).first

    editor.click()
    editor.fill(post["body"])

    print("✓ Body", flush=True)

    # IMAGE
    img = download_image(post.get("image"))

    if img:
        try:
            page.locator(
                'input[type="file"]'
            ).first.set_input_files(img)

            page.wait_for_timeout(2500)

            print("✓ Image", flush=True)

        except Exception as e:
            print(
                f"Image upload skipped: {e}",
                flush=True
            )

    # FIRST PUBLISH
    page.get_by_text(
        "Publish",
        exact=True
    ).last.click(force=True)

    print(
        "✓ FIRST PUBLISH",
        flush=True
    )

    page.wait_for_timeout(2500)

    # CATEGORY
    try:
        selector = page.get_by_text(
            "Select category",
            exact=True
        ).first

        if selector.count() > 0:
            selector.click(force=True)

            page.wait_for_timeout(500)

            option = page.get_by_text(
                post["category"],
                exact=True
            ).last

            if option.count() > 0:
                option.click(force=True)

                print(
                    f"✓ Category: {post['category']}",
                    flush=True
                )

    except Exception:
        pass

    # FINAL PUBLISH
    buttons = page.locator("button")
    final = None

    for i in range(buttons.count()):

        button = buttons.nth(i)

        try:
            if (
                button.is_visible()
                and button.inner_text().strip().lower()
                == "publish"
            ):
                final = button

        except:
            pass

    if not final:
        print(
            "❌ Final Publish button missing",
            flush=True
        )
        return None

    final.click(force=True)

    print(
        "✓ FINAL PUBLISH",
        flush=True
    )

    # WAIT FOR AUTHORS URL
    for _ in range(12):

        page.wait_for_timeout(3000)

        url = page.url

        print(
            f"URL: {url}",
            flush=True
        )

        if re.match(
            r"https://bengali\.serey\.io/authors/[^/]+/[^/?#]+",
            url
        ):
            print(
                f"✓ PUBLISHED SUCCESSFULLY: {url}",
                flush=True
            )

            return url

    print(
        "❌ Serey did not redirect to /authors/...",
        flush=True
    )

    return None


def main():

    print("=" * 50)
    print("STEEM → SEREY AUTO SYNC")
    print("=" * 50)

    synced = load_synced()

    posts = get_last_1000_posts()

    new_posts = [
        p for p in posts
        if p["id"] not in synced
    ]

    print(
        f"Previously synced: {len(synced)}",
        flush=True
    )

    print(
        f"Unsynced in last 1000: {len(new_posts)}",
        flush=True
    )

    if not new_posts:
        print(
            "No new posts in last 1000.",
            flush=True
        )
        return

    # OLD → NEW
    post = new_posts[0]

    print(
        f"Next post: {post['title']}",
        flush=True
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1280,
                "height": 900
            }
        )

        try:

            login(page)

            url = publish(
                page,
                post
            )

            if url:

                synced.add(post["id"])
                save_synced(synced)

                print(
                    f"✓ SAVED: {post['id']}",
                    flush=True
                )

            else:

                print(
                    "⚠ NOT SAVED — will retry next run.",
                    flush=True
                )

        finally:

            browser.close()

    print("=" * 50)
    print("SYNC COMPLETED")
    print("=" * 50)


if __name__ == "__main__":
    main()
