import os
import json
import re
import time
import requests
from playwright.sync_api import sync_playwright


# ============================================================
# SETTINGS
# ============================================================

STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD", ""
).strip()

SEREY_BASE = "https://bengali.serey.io"
NEW_POST_URL = f"{SEREY_BASE}/blog/post/new"


# ============================================================
# STEEM RPC
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


def rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
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
                timeout=20
            )

            r.raise_for_status()

            data = r.json()

            if "error" in data:
                raise RuntimeError(
                    str(data["error"])
                )

            return data["result"]

        except Exception as e:

            print(
                f"RPC failed: {e}",
                flush=True
            )

    raise RuntimeError(
        "All Steem RPC nodes failed."
    )


# ============================================================
# GET ONE UNSYNCED POST
# ============================================================

def get_one_post():

    print(
        f"\nGetting latest post from @{STEEM_USERNAME}...",
        flush=True
    )

    result = rpc(
        "condenser_api.get_discussions_by_blog",
        {
            "tag": STEEM_USERNAME,
            "limit": 10
        }
    )

    for post in result:

        if post.get("author") == STEEM_USERNAME:

            print(
                "\nTEST POST:",
                post.get("title"),
                flush=True
            )

            return post

    return None


# ============================================================
# LOGIN
# ============================================================

def login(page):

    print(
        "\nLogging into Serey...",
        flush=True
    )

    try:

        page.goto(
            SEREY_BASE,
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
            force=True,
            timeout=10000
        )

        page.wait_for_timeout(2500)

        page.locator(
            'input[placeholder*="Username" i]'
        ).first.fill(
            SEREY_LOGIN
        )

        page.locator(
            'input[placeholder*="Private Key" i], '
            'input[placeholder*="Password" i]'
        ).first.fill(
            SEREY_PASSWORD
        )

        page.locator(
            '.ant-modal-content button:has-text("Log in"), '
            '.ant-modal-content button:has-text("Log In"), '
            'button:has-text("Log in"), '
            'button:has-text("Log In")'
        ).last.click(
            force=True,
            timeout=10000
        )

        page.wait_for_timeout(6000)

        print(
            "✓ LOGIN SUCCESS",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"❌ LOGIN FAILED: {e}",
            flush=True
        )

        return False


# ============================================================
# DEBUG PAGE
# ============================================================

def debug_page(page):

    print("\n" + "=" * 70)
    print("SEREY UI DIAGNOSTIC START")
    print("=" * 70)

    print(
        f"\nCURRENT URL:\n{page.url}",
        flush=True
    )

    # --------------------------------------------------------
    # BODY TEXT
    # --------------------------------------------------------

    print(
        "\n===== VISIBLE PAGE TEXT =====",
        flush=True
    )

    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        print(
            text[:15000],
            flush=True
        )

    except Exception as e:

        print(
            f"Body text error: {e}",
            flush=True
        )

    # --------------------------------------------------------
    # BUTTONS
    # --------------------------------------------------------

    print(
        "\n===== BUTTONS =====",
        flush=True
    )

    try:

        buttons = page.locator(
            "button"
        )

        count = buttons.count()

        print(
            f"Button count: {count}",
            flush=True
        )

        for i in range(
            min(count, 100)
        ):

            try:

                b = buttons.nth(i)

                if not b.is_visible(
                    timeout=200
                ):
                    continue

                print(
                    f"\nBUTTON #{i}",
                    flush=True
                )

                print(
                    "TEXT:",
                    repr(
                        b.inner_text(
                            timeout=500
                        )
                    ),
                    flush=True
                )

                print(
                    "TYPE:",
                    b.get_attribute(
                        "type"
                    ),
                    flush=True
                )

                print(
                    "CLASS:",
                    b.get_attribute(
                        "class"
                    ),
                    flush=True
                )

                print(
                    "ARIA:",
                    b.get_attribute(
                        "aria-label"
                    ),
                    flush=True
                )

                print(
                    "HTML:",
                    (
                        b.evaluate(
                            "(e) => e.outerHTML"
                        )[:2000]
                    ),
                    flush=True
                )

            except Exception:
                pass

    except Exception as e:

        print(
            f"Button debug error: {e}",
            flush=True
        )

    # --------------------------------------------------------
    # INPUTS
    # --------------------------------------------------------

    print(
        "\n===== INPUTS =====",
        flush=True
    )

    try:

        inputs = page.locator(
            "input"
        )

        count = inputs.count()

        print(
            f"Input count: {count}",
            flush=True
        )

        for i in range(
            min(count, 100)
        ):

            try:

                x = inputs.nth(i)

                if not x.is_visible(
                    timeout=200
                ):
                    continue

                print(
                    f"\nINPUT #{i}",
                    flush=True
                )

                print(
                    "TYPE:",
                    x.get_attribute(
                        "type"
                    ),
                    flush=True
                )

                print(
                    "PLACEHOLDER:",
                    x.get_attribute(
                        "placeholder"
                    ),
                    flush=True
                )

                print(
                    "NAME:",
                    x.get_attribute(
                        "name"
                    ),
                    flush=True
                )

                print(
                    "CLASS:",
                    x.get_attribute(
                        "class"
                    ),
                    flush=True
                )

                print(
                    "ARIA:",
                    x.get_attribute(
                        "aria-label"
                    ),
                    flush=True
                )

                print(
                    "HTML:",
                    (
                        x.evaluate(
                            "(e) => e.outerHTML"
                        )[:2000]
                    ),
                    flush=True
                )

            except Exception:
                pass

    except Exception as e:

        print(
            f"Input debug error: {e}",
            flush=True
        )

    # --------------------------------------------------------
    # SELECT / COMBOBOX
    # --------------------------------------------------------

    print(
        "\n===== SELECT / COMBOBOX =====",
        flush=True
    )

    selectors = [
        "select",
        "[role='combobox']",
        "[role='listbox']",
        "[role='option']",
        ".ant-select",
        ".ant-select-selector",
        ".ant-select-dropdown"
    ]

    for selector in selectors:

        try:

            loc = page.locator(
                selector
            )

            count = loc.count()

            print(
                f"\n{selector} -> {count}",
                flush=True
            )

            for i in range(
                min(count, 50)
            ):

                try:

                    item = loc.nth(i)

                    if not item.is_visible(
                        timeout=200
                    ):
                        continue

                    print(
                        f"\n#{i}",
                        flush=True
                    )

                    print(
                        "TEXT:",
                        repr(
                            item.inner_text(
                                timeout=500
                            )
                        ),
                        flush=True
                    )

                    print(
                        "CLASS:",
                        item.get_attribute(
                            "class"
                        ),
                        flush=True
                    )

                    print(
                        "ARIA:",
                        item.get_attribute(
                            "aria-label"
                        ),
                        flush=True
                    )

                    print(
                        "HTML:",
                        (
                            item.evaluate(
                                "(e) => e.outerHTML"
                            )[:3000]
                        ),
                        flush=True
                    )

                except Exception:
                    pass

        except Exception:
            pass

    # --------------------------------------------------------
    # TEXT SEARCH
    # --------------------------------------------------------

    print(
        "\n===== CATEGORY TEXT SEARCH =====",
        flush=True
    )

    for keyword in [
        "Select category",
        "Category",
        "Select sub category",
        "Sub Category",
        "Society",
        "Life",
        "Publish",
        "Post to Blockchain"
    ]:

        try:

            loc = page.get_by_text(
                keyword,
                exact=False
            )

            count = loc.count()

            print(
                f"\n'{keyword}' -> {count}",
                flush=True
            )

            for i in range(
                min(count, 20)
            ):

                try:

                    item = loc.nth(i)

                    print(
                        f"#{i} visible="
                        f"{item.is_visible(timeout=200)}",
                        flush=True
                    )

                    if item.is_visible(
                        timeout=200
                    ):

                        print(
                            "HTML:",
                            (
                                item.evaluate(
                                    "(e) => e.outerHTML"
                                )[:3000]
                            ),
                            flush=True
                        )

                except Exception:
                    pass

        except Exception:
            pass

    # --------------------------------------------------------
    # PAGE HTML FILE
    # --------------------------------------------------------

    try:

        with open(
            "serey_debug.html",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                page.content()
            )

        print(
            "\n✓ Saved serey_debug.html",
            flush=True
        )

    except Exception as e:

        print(
            f"HTML save failed: {e}",
            flush=True
        )

    print(
        "\n" + "=" * 70
    )

    print(
        "SEREY UI DIAGNOSTIC END"
    )

    print(
        "=" * 70
    )


# ============================================================
# TEST
# ============================================================

def main():

    print(
        "=" * 70
    )

    print(
        "STEEM -> SEREY DIAGNOSTIC TEST"
    )

    print(
        "NO FINAL PUBLISH WILL BE CLICKED"
    )

    print(
        "=" * 70
    )

    post = get_one_post()

    if not post:

        print(
            "No Steem post found."
        )

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

        if not login(page):

            browser.close()
            return

        # ----------------------------------------------------
        # OPEN NEW POST
        # ----------------------------------------------------

        page.goto(
            NEW_POST_URL,
            timeout=60000,
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(3000)

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        page.locator(
            'input[placeholder*="title" i]'
        ).first.fill(
            post.get(
                "title",
                ""
            )
        )

        print(
            "✓ Title filled",
            flush=True
        )

        # ----------------------------------------------------
        # BODY
        # ----------------------------------------------------

        body = post.get(
            "body",
            ""
        )

        # Remove Steem markdown images
        body = re.sub(
            r'!\[[^\]]*\]\([^)]+\)',
            '',
            body
        )

        page.locator(
            'div[contenteditable="true"], textarea'
        ).first.fill(
            body
        )

        print(
            "✓ Body filled",
            flush=True
        )

        page.wait_for_timeout(1500)

        # ----------------------------------------------------
        # FIRST PUBLISH ONLY
        # ----------------------------------------------------

        first = page.locator(
            'button:has-text("Publish")'
        ).first

        first.click(
            force=True,
            timeout=10000
        )

        print(
            "✓ FIRST PUBLISH CLICKED",
            flush=True
        )

        # Wait for category screen
        page.wait_for_timeout(
            4000
        )

        # ----------------------------------------------------
        # DIAGNOSTIC
        # ----------------------------------------------------

        debug_page(page)

        # IMPORTANT:
        # We DO NOT click final publish.
        # We DO NOT save synced_posts.json.

        browser.close()

    print(
        "\nDIAGNOSTIC FINISHED."
    )

    print(
        "No post was marked as synced."
    )


if __name__ == "__main__":
    main()
