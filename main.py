import os
import json
import re
import requests
from playwright.sync_api import sync_playwright


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

    except Exception as e:
        print(f"⚠️ synced_posts.json error: {e}", flush=True)

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
        print(f"❌ Database save failed: {e}", flush=True)


# ============================================================
# CLEAN STEEM POST
# ============================================================

def clean_post(body):

    image_url = None

    # Markdown image
    match = re.search(
        r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
        body,
        re.I
    )

    if match:
        image_url = match.group(1)

    # Direct image URL
    if not image_url:

        match = re.search(
            r'https?://[^\s"\']+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s"\']*)?',
            body,
            re.I
        )

        if match:
            image_url = match.group(0)

    # Remove markdown images
    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        body
    )

    # Remove image URLs
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

        r = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if r.status_code == 200:

            with open(TEMP_IMAGE, "wb") as f:
                f.write(r.content)

            print("✓ থাম্বনেইল ডাউনলোড হয়েছে।", flush=True)

            return os.path.abspath(TEMP_IMAGE)

    except Exception as e:

        print(
            f"⚠️ Image download failed: {e}",
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

            r = requests.post(
                node,
                json=payload,
                timeout=30
            )

            r.raise_for_status()

            result = r.json().get(
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

    return []


# ============================================================
# LOGIN BUTTON FINDER
# ============================================================

def get_login_button(page):

    # IMPORTANT:
    # CSS selector এবং text locator আলাদা রাখা হয়েছে।

    selectors = [
        'button:has-text("Log in")',
        'button:has-text("Log In")'
    ]

    for selector in selectors:

        try:

            locator = page.locator(selector)

            if locator.count() > 0:

                for i in range(locator.count()):

                    try:

                        button = locator.nth(i)

                        if button.is_visible(
                            timeout=1000
                        ):
                            return button

                    except:
                        pass

        except:
            pass

    # Text locator fallback
    try:

        locator = page.get_by_text(
            "Log in",
            exact=True
        )

        if locator.count() > 0:

            for i in range(locator.count()):

                try:

                    item = locator.nth(i)

                    if item.is_visible(
                        timeout=1000
                    ):
                        return item

                except:
                    pass

    except:
        pass

    try:

        locator = page.get_by_text(
            "Log In",
            exact=True
        )

        if locator.count() > 0:

            for i in range(locator.count()):

                try:

                    item = locator.nth(i)

                    if item.is_visible(
                        timeout=1000
                    ):
                        return item

                except:
                    pass

    except:
        pass

    return None


# ============================================================
# CHECK LOGIN
# ============================================================

def is_logged_in(page):

    try:

        page.goto(
            SEREY,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(5000)

        login_button = get_login_button(page)

        if login_button is not None:

            return False

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

    # --------------------------------------------------------
    # Check existing session
    # --------------------------------------------------------

    try:

        if is_logged_in(page):

            print(
                "✓ অলরেডি লগইন আছে।",
                flush=True
            )

            return True

    except:
        pass

    # --------------------------------------------------------
    # Login
    # --------------------------------------------------------

    print(
        "⌛ Serey-তে লগইন করা হচ্ছে...",
        flush=True
    )

    try:

        login_button = get_login_button(page)

        if login_button is None:

            print(
                "❌ Log in button পাওয়া যায়নি।",
                flush=True
            )

            return False

        login_button.click(
            force=True,
            timeout=15000
        )

        page.wait_for_timeout(2500)

        # Username
        username_input = page.locator(
            'input[placeholder*="Username" i]'
        ).first

        username_input.wait_for(
            state="visible",
            timeout=15000
        )

        username_input.fill(
            SEREY_LOGIN
        )

        # Private Key / Password
        password_input = page.locator(
            'input[placeholder*="Private Key" i]'
        ).first

        if password_input.count() == 0:

            password_input = page.locator(
                'input[type="password"]'
            ).first

        password_input.wait_for(
            state="visible",
            timeout=15000
        )

        password_input.fill(
            SEREY_PASSWORD
        )

        # ----------------------------------------------------
        # Login submit
        # ----------------------------------------------------

        login_submit = page.locator(
            'button:has-text("Log in")'
        )

        if login_submit.count() == 0:

            login_submit = page.locator(
                'button:has-text("Log In")'
            )

        if login_submit.count() == 0:

            print(
                "❌ Login submit button পাওয়া যায়নি।",
                flush=True
            )

            return False

        # শেষ visible login button
        clicked = False

        for i in range(
            login_submit.count() - 1,
            -1,
            -1
        ):

            try:

                btn = login_submit.nth(i)

                if btn.is_visible(
                    timeout=1000
                ):

                    btn.click(
                        force=True,
                        timeout=15000
                    )

                    clicked = True
                    break

            except:
                pass

        if not clicked:

            print(
                "❌ Login button click করা যায়নি।",
                flush=True
            )

            return False

        page.wait_for_timeout(8000)

        # ----------------------------------------------------
        # Verify login
        # ----------------------------------------------------

        login_button_after = get_login_button(page)

        if login_button_after is None:

            print(
                "✓ লগইন সম্পন্ন।",
                flush=True
            )

            return True

        print(
            "❌ Login verify করা যায়নি।",
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
# FIND PUBLISH BUTTONS
# ============================================================

def find_publish_buttons(page):

    buttons = []

    selectors = [
        'button:has-text("Publish")',
        'button:has-text("publish")'
    ]

    for selector in selectors:

        try:

            locator = page.locator(selector)

            for i in range(locator.count()):

                try:

                    btn = locator.nth(i)

                    if btn.is_visible(
                        timeout=500
                    ):
                        buttons.append(btn)

                except:
                    pass

        except:
            pass

    # Duplicate element remove
    unique = []

    for btn in buttons:

        try:

            if not any(
                btn == x
                for x in unique
            ):
                unique.append(btn)

        except:
            unique.append(btn)

    return unique


# ============================================================
# CLICK FINAL PUBLISH
# ============================================================

def click_final_publish(page):

    print(
        "⌛ AI ক্যাটাগরি প্রসেসিং হচ্ছে "
        "(৯০ সেকেন্ড পর্যন্ত অপেক্ষা)...",
        flush=True
    )

    for attempt in range(18):

        page.wait_for_timeout(5000)

        buttons = find_publish_buttons(page)

        print(
            f"🔎 Visible Publish buttons: {len(buttons)}",
            flush=True
        )

        # ----------------------------------------------------
        # সাধারণভাবে modal আসলে 2টি Publish button থাকবে
        # ----------------------------------------------------

        if len(buttons) >= 2:

            try:

                final_button = buttons[-1]

                final_button.scroll_into_view_if_needed()

                page.wait_for_timeout(1500)

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
                    f"⚠️ Final Publish retry: {e}",
                    flush=True
                )

        # ----------------------------------------------------
        # কিছু ক্ষেত্রে modal-এর button count আলাদা হতে পারে
        # ----------------------------------------------------

        elif len(buttons) == 1:

            try:

                body_text = page.locator(
                    "body"
                ).inner_text(
                    timeout=3000
                )

                category_words = [
                    "AI category",
                    "AI Category",
                    "category",
                    "Category"
                ]

                category_found = any(
                    word in body_text
                    for word in category_words
                )

                if category_found:

                    buttons[0].scroll_into_view_if_needed()

                    page.wait_for_timeout(1500)

                    buttons[0].click(
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
            f"⌛ Final Publish অপেক্ষা... "
            f"{(attempt + 1) * 5}s",
            flush=True
        )

    print(
        "❌ Final Publish button পাওয়া যায়নি।",
        flush=True
    )

    return False


# ============================================================
# VERIFY PUBLISHED POST
# ============================================================

def verify_publish(page, title):

    print(
        "⌛ পোস্ট ভেরিফাই করা হচ্ছে...",
        flush=True
    )

    # 2 মিনিট পর্যন্ত verification
    for i in range(24):

        page.wait_for_timeout(5000)

        current_url = page.url

        print(
            f"🔎 Verification {i + 1}/24",
            flush=True
        )

        print(
            f"   URL: {current_url}",
            flush=True
        )

        # ----------------------------------------------------
        # URL changed
        # ----------------------------------------------------

        if (
            current_url != NEW_POST_URL
            and "/blog/post/new" not in current_url
        ):

            if (
                "/post/" in current_url
                or "/blog/" in current_url
                or "/@" in current_url
                or "/authors/" in current_url
            ):

                print(
                    "✅ পোস্ট সফলভাবে publish হয়েছে!",
                    flush=True
                )

                print(
                    f"🔗 {current_url}",
                    flush=True
                )

                return True

        # ----------------------------------------------------
        # Success text
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=3000
            )

            success_messages = [
                "Successfully posted",
                "Successfully published",
                "Post published",
                "Article published",
                "Published successfully",
                "Your post has been published",
                "successfully posted"
            ]

            for message in success_messages:

                if message.lower() in body_text.lower():

                    print(
                        "✅ Success message পাওয়া গেছে।",
                        flush=True
                    )

                    return True

        except:
            pass

        # ----------------------------------------------------
        # Title found
        # ----------------------------------------------------

        try:

            if title:

                title_locator = page.get_by_text(
                    title,
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

                                if (
                                    page.url != NEW_POST_URL
                                    and "/new" not in page.url
                                ):

                                    print(
                                        "✅ Published post title পাওয়া গেছে।",
                                        flush=True
                                    )

                                    print(
                                        f"🔗 {page.url}",
                                        flush=True
                                    )

                                    return True

                        except:
                            pass

        except:
            pass

    # --------------------------------------------------------
    # IMPORTANT:
    # এখানে আর True করা হবে না
    # --------------------------------------------------------

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
        # New post page
        # ----------------------------------------------------

        page.goto(
            NEW_POST_URL,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # Title
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
        # Editor
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
        # Image
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
                    f"⚠️ Thumbnail upload failed: {e}",
                    flush=True
                )

        # ----------------------------------------------------
        # FIRST PUBLISH
        # ----------------------------------------------------

        print(
            "✓ প্রথমবার Publish ক্লিক করা হচ্ছে...",
            flush=True
        )

        buttons = find_publish_buttons(page)

        if not buttons:

            print(
                "❌ প্রথম Publish button পাওয়া যায়নি।",
                flush=True
            )

            return False

        buttons[0].scroll_into_view_if_needed()

        buttons[0].click(
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

        final_success = click_final_publish(
            page
        )

        if not final_success:

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

        print(
            "❌ POST SYNC FAILED.",
            flush=True
        )

        print(
            "ℹ️ synced_posts.json-এ পোস্ট যোগ করা হয়নি।",
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
        # PUBLISH
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
                    "ℹ️ এই পোস্ট synced database-এ যোগ করা হয়নি।",
                    flush=True
                )

        browser.close()

    # --------------------------------------------------------
    # Cleanup
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
