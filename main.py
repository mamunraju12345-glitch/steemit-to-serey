import os
import json
import re
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# STEEM -> SEREY AUTO SYNC
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get("SEREY_USERNAME", "").replace("@", "").strip()
SEREY_PASSWORD = os.environ.get("SEREY_PASSWORD", "").strip()

SEREY = "https://serey.io"
NEW_POST_URL = f"{SEREY}/blog/post/new"

SYNC_FILE = "synced_posts.json"
TEMP_IMAGE = "temp_image.jpg"

# প্রতি Run-এ কয়টি পোস্ট publish করবে
POSTS_PER_RUN = 1

STEEM_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com"
]


# ============================================================
# SYNC DATABASE
# ============================================================

def load_synced():
    if not os.path.exists(SYNC_FILE):
        return set()

    try:
        with open(SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        return set()

    except Exception as e:
        print(f"⚠️ synced_posts.json পড়তে সমস্যা: {e}", flush=True)
        return set()


def save_synced(data):
    try:
        with open(SYNC_FILE, "w", encoding="utf-8") as f:
            json.dump(
                sorted(list(data)),
                f,
                ensure_ascii=False,
                indent=2
            )

        print("✓ Sync database updated.", flush=True)

    except Exception as e:
        print(f"❌ Sync database save failed: {e}", flush=True)


# ============================================================
# CLEAN STEEM POST
# ============================================================

def clean_post(body):

    image_url = None

    # Markdown image খুঁজবে
    markdown_image = re.search(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        body,
        re.I
    )

    if markdown_image:
        image_url = markdown_image.group(1)

    # সাধারণ image URL খুঁজবে
    if not image_url:
        image_match = re.search(
            r'https?://[^\s"\']+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s"\']*)?',
            body,
            re.I
        )

        if image_match:
            image_url = image_match.group(0)

    # Markdown image remove
    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    # সরাসরি image URL remove
    clean_body = re.sub(
        r'https?://[^\s"\']+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s"\']*)?',
        '',
        clean_body,
        flags=re.I
    )

    return clean_body.strip(), image_url


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    if not url:
        return None

    try:

        print("⌛ থাম্বনেইল ডাউনলোড করা হচ্ছে...", flush=True)

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if response.status_code == 200:

            with open(TEMP_IMAGE, "wb") as f:
                f.write(response.content)

            print("✓ থাম্বনেইল ডাউনলোড হয়েছে।", flush=True)

            return os.path.abspath(TEMP_IMAGE)

    except Exception as e:

        print(
            f"⚠️ ইমেজ ডাউনলোড করা যায়নি: {e}",
            flush=True
        )

    return None


# ============================================================
# GET STEEM POSTS
# ============================================================

def get_steem_posts():

    print(
        f"Checking posts for @{STEEM_USERNAME}...",
        flush=True
    )

    payload = {
        "jsonrpc": "2.0",
        "method": "condenser_api.get_discussions_by_blog",
        "params": {
            "tag": STEEM_USERNAME,
            "limit": 20
        },
        "id": 1
    }

    for node in STEEM_NODES:

        try:

            print(
                f"RPC: {node}",
                flush=True
            )

            response = requests.post(
                node,
                json=payload,
                timeout=30
            )

            response.raise_for_status()

            result = response.json().get(
                "result",
                []
            )

            posts = []

            for p in result:

                if p.get("author") != STEEM_USERNAME:
                    continue

                body, image = clean_post(
                    p.get("body", "")
                )

                posts.append({
                    "id": f"{p['author']}/{p['permlink']}",
                    "title": p.get("title", "").strip(),
                    "body": body,
                    "image": image
                })

            return posts

        except Exception as e:

            print(
                f"⚠️ RPC failed: {e}",
                flush=True
            )

    print(
        "❌ সব Steem RPC node failed.",
        flush=True
    )

    return []


# ============================================================
# FIND LOGIN STATE
# ============================================================

def is_logged_in(page):

    try:

        page.goto(
            SEREY,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(4000)

        # Login button থাকলে logged out
        login_buttons = page.locator(
            'button:has-text("Log in"), '
            'button:has-text("Log In"), '
            'text="Log in", '
            'text="Log In"'
        )

        if login_buttons.count() > 0:

            for i in range(
                min(login_buttons.count(), 5)
            ):

                try:

                    if login_buttons.nth(i).is_visible(
                        timeout=1000
                    ):
                        return False

                except:
                    pass

        return True

    except Exception as e:

        print(
            f"⚠️ Login status check problem: {e}",
            flush=True
        )

        return False


# ============================================================
# SEREY LOGIN
# ============================================================

def login_serey(page):

    print(
        "Serey-তে লগইন চেক করা হচ্ছে...",
        flush=True
    )

    try:

        if is_logged_in(page):

            print(
                "✓ অলরেডি লগইন আছে।",
                flush=True
            )

            return True

    except:
        pass

    print(
        "⌛ Serey-তে লগইন করা হচ্ছে...",
        flush=True
    )

    try:

        page.goto(
            SEREY,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(3000)

        login_button = page.locator(
            'button:has-text("Log in"), '
            'button:has-text("Log In"), '
            'text="Log in", '
            'text="Log In"'
        ).first

        login_button.click(
            force=True,
            timeout=10000
        )

        page.wait_for_timeout(2000)

        # Username
        username_input = page.locator(
            'input[placeholder*="Username" i]'
        ).first

        username_input.fill(
            SEREY_LOGIN
        )

        # Private Key / Password
        password_input = page.locator(
            'input[placeholder*="Private Key" i], '
            'input[type="password"]'
        ).first

        password_input.fill(
            SEREY_PASSWORD
        )

        # Login
        page.locator(
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        ).last.click(
            force=True
        )

        page.wait_for_timeout(8000)

        if is_logged_in(page):

            print(
                "✓ লগইন সম্পন্ন।",
                flush=True
            )

            return True

        print(
            "❌ Serey login verify করা যায়নি।",
            flush=True
        )

        return False

    except Exception as e:

        print(
            f"❌ Login failed: {e}",
            flush=True
        )

        return False


# ============================================================
# WAIT FOR PUBLISH MODAL
# ============================================================

def find_publish_buttons(page):

    selectors = [
        'button:has-text("Publish")',
        'button:has-text("publish")'
    ]

    buttons = []

    for selector in selectors:

        try:

            locator = page.locator(selector)

            count = locator.count()

            for i in range(count):

                try:

                    button = locator.nth(i)

                    if button.is_visible(
                        timeout=500
                    ):

                        buttons.append(button)

                except:
                    pass

        except:
            pass

    return buttons


# ============================================================
# CLICK FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    print(
        "⌛ AI ক্যাটাগরি প্রসেসিং হচ্ছে "
        "(১ মিনিট পর্যন্ত অপেক্ষা)...",
        flush=True
    )

    # সর্বোচ্চ 90 sec অপেক্ষা
    for attempt in range(18):

        page.wait_for_timeout(5000)

        buttons = find_publish_buttons(page)

        # একাধিক Publish button থাকলে
        # শেষ visible button ব্যবহার করা হবে
        if len(buttons) >= 2:

            try:

                final_button = buttons[-1]

                if final_button.is_visible(
                    timeout=1000
                ):

                    print(
                        "✓ ফাইনাল Publish button পাওয়া গেছে।",
                        flush=True
                    )

                    page.wait_for_timeout(2000)

                    final_button.click(
                        force=True,
                        timeout=15000
                    )

                    print(
                        "✓ ফাইনাল Publish বাটনে ক্লিক করা হয়েছে।",
                        flush=True
                    )

                    return True

            except Exception as e:

                print(
                    f"⚠️ Final Publish click retry: {e}",
                    flush=True
                )

        # কখনও modal-এ শুধু একটি visible button থাকতে পারে
        elif len(buttons) == 1:

            try:

                button = buttons[0]

                # নতুন modal আছে কিনা বোঝার চেষ্টা
                text = page.locator(
                    "body"
                ).inner_text(timeout=3000)

                if (
                    "AI" in text
                    or "Category" in text
                    or "category" in text
                ):

                    button.click(
                        force=True,
                        timeout=15000
                    )

                    print(
                        "✓ ফাইনাল Publish বাটনে ক্লিক করা হয়েছে।",
                        flush=True
                    )

                    return True

            except:
                pass

        print(
            f"⌛ Publish button অপেক্ষা... "
            f"{(attempt + 1) * 5}s",
            flush=True
        )

    print(
        "❌ 90 সেকেন্ডেও Final Publish button পাওয়া যায়নি।",
        flush=True
    )

    return False


# ============================================================
# VERIFY SUCCESS
# ============================================================

def verify_publish(page, original_title):

    print(
        "⌛ পোস্ট ভেরিফাই করা হচ্ছে...",
        flush=True
    )

    # প্রথমে current page URL check
    for i in range(24):

        page.wait_for_timeout(5000)

        current_url = page.url

        print(
            f"🔎 Verification {i + 1}/24: {current_url}",
            flush=True
        )

        # ----------------------------------------------------
        # 1. URL থেকে success
        # ----------------------------------------------------

        if (
            current_url != NEW_POST_URL
            and "/blog/post/new" not in current_url
        ):

            # login / home page নয় কিনা
            if (
                "/post/" in current_url
                or "/blog/" in current_url
                or "/@" in current_url
                or "/authors/" in current_url
            ):

                print(
                    f"✅ পোস্ট সফলভাবে publish হয়েছে!",
                    flush=True
                )

                print(
                    f"🔗 URL: {current_url}",
                    flush=True
                )

                return True

        # ----------------------------------------------------
        # 2. Success message
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text(timeout=3000)

            success_words = [
                "Successfully posted",
                "Successfully published",
                "Post published",
                "Article published",
                "Published successfully",
                "Your post has been published",
                "successfully posted"
            ]

            for word in success_words:

                if word.lower() in body_text.lower():

                    print(
                        "✅ Success message পাওয়া গেছে।",
                        flush=True
                    )

                    return True

        except:
            pass

        # ----------------------------------------------------
        # 3. Title page-এ দেখা গেলে success
        # ----------------------------------------------------

        try:

            if original_title:

                title_locator = page.get_by_text(
                    original_title,
                    exact=False
                )

                if title_locator.count() > 0:

                    for j in range(
                        min(title_locator.count(), 5)
                    ):

                        try:

                            if title_locator.nth(j).is_visible(
                                timeout=500
                            ):

                                current_url = page.url

                                if (
                                    "/new" not in current_url
                                    and current_url != NEW_POST_URL
                                ):

                                    print(
                                        "✅ পোস্টের title পাওয়া গেছে।",
                                        flush=True
                                    )

                                    print(
                                        f"🔗 URL: {current_url}",
                                        flush=True
                                    )

                                    return True

                        except:
                            pass

        except:
            pass

    # ========================================================
    # IMPORTANT:
    # Verification failed হলে TRUE হবে না
    # ========================================================

    print(
        "❌ Verification failed: পোস্ট নিশ্চিতভাবে পাওয়া যায়নি।",
        flush=True
    )

    return False


# ============================================================
# PUBLISH PROCESS
# ============================================================

def publish_process(page, post):

    print(
        f"\n🚀 সিঙ্কিং শুরু: {post['title']}",
        flush=True
    )

    try:

        # ----------------------------------------------------
        # NEW POST PAGE
        # ----------------------------------------------------

        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title_input = page.locator(
            'input[placeholder*="Enter title" i]'
        ).first

        title_input.wait_for(
            state="visible",
            timeout=30000
        )

        title_input.fill(
            post["title"]
        )

        # ----------------------------------------------------
        # CONTENT
        # ----------------------------------------------------

        editor = page.locator(
            'div[contenteditable="true"]'
        ).first

        editor.wait_for(
            state="visible",
            timeout=30000
        )

        editor.click()

        editor.fill(
            post["body"]
        )

        print(
            "✓ টাইটেল ও কন্টেন্ট যুক্ত হয়েছে।",
            flush=True
        )

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        image_path = download_image(
            post["image"]
        )

        if image_path:

            try:

                file_input = page.locator(
                    'input[type="file"]'
                ).first

                file_input.set_input_files(
                    image_path
                )

                page.wait_for_timeout(7000)

                print(
                    "✓ থাম্বনেইল আপলোড হয়েছে।",
                    flush=True
                )

            except Exception as e:

                print(
                    f"⚠️ থাম্বনেইল upload failed: {e}",
                    flush=True
                )

        # ----------------------------------------------------
        # FIRST PUBLISH
        # ----------------------------------------------------

        print(
            "✓ প্রথমবার Publish ক্লিক করা হচ্ছে...",
            flush=True
        )

        publish_buttons = find_publish_buttons(page)

        if not publish_buttons:

            print(
                "❌ প্রথম Publish button পাওয়া যায়নি।",
                flush=True
            )

            return False

        # প্রথম visible Publish
        first_publish = publish_buttons[0]

        first_publish.click(
            force=True,
            timeout=15000
        )

        print(
            "✓ প্রথম Publish click হয়েছে।",
            flush=True
        )

        # ----------------------------------------------------
        # FINAL PUBLISH
        # ----------------------------------------------------

        if not click_final_publish(page):

            print(
                "❌ Final Publish সম্পন্ন হয়নি।",
                flush=True
            )

            return False

        # ----------------------------------------------------
        # VERIFY
        # ----------------------------------------------------

        verified = verify_publish(
            page,
            post["title"]
        )

        if verified:

            print(
                "🎉 POST SYNC SUCCESSFUL!",
                flush=True
            )

            return True

        # ----------------------------------------------------
        # VERY IMPORTANT
        # ----------------------------------------------------
        # Verification failed = False
        # synced_posts.json update হবে না
        # ----------------------------------------------------

        print(
            "❌ POST SYNC FAILED — synced database-এ যোগ করা হয়নি।",
            flush=True
        )

        return False

    except Exception as e:

        print(
            f"❌ Publishing error: {e}",
            flush=True
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    synced = load_synced()

    all_posts = get_steem_posts()

    print(
        f"Total posts: {len(all_posts)}",
        flush=True
    )

    to_sync = [
        p
        for p in all_posts
        if p["id"] not in synced
    ][:POSTS_PER_RUN]

    print(
        f"Unsynced posts: {len(to_sync)}",
        flush=True
    )

    if not to_sync:

        print(
            "নতুন কোনো unsynced post নেই।",
            flush=True
        )

        return

    print(
        f"Publishing this run: {len(to_sync)}",
        flush=True
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1280,
                "height": 900
            }
        )

        page = context.new_page()

        # ----------------------------------------------------
        # LOGIN
        # ----------------------------------------------------

        if not login_serey(page):

            print(
                "❌ Serey login failed. Sync বন্ধ করা হচ্ছে।",
                flush=True
            )

            browser.close()
            return

        # ----------------------------------------------------
        # PUBLISH POSTS
        # ----------------------------------------------------

        for post in to_sync:

            success = publish_process(
                page,
                post
            )

            if success:

                synced.add(
                    post["id"]
                )

                save_synced(
                    synced
                )

                print(
                    f"✓ Synced: {post['id']}",
                    flush=True
                )

            else:

                print(
                    f"⚠️ Failed: {post['id']}",
                    flush=True
                )

                print(
                    "ℹ️ এই পোস্ট synced database-এ যোগ করা হয়নি। "
                    "পরের run-এ আবার চেষ্টা করবে।",
                    flush=True
                )

        browser.close()

    # --------------------------------------------------------
    # TEMP IMAGE CLEANUP
    # --------------------------------------------------------

    if os.path.exists(TEMP_IMAGE):

        try:
            os.remove(TEMP_IMAGE)
        except:
            pass

    print(
        "\n============================================================",
        flush=True
    )

    print(
        "SYNC RUN FINISHED",
        flush=True
    )

    print(
        "============================================================",
        flush=True
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
