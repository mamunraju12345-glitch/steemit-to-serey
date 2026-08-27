import os
import json
import requests
import time
import re
from playwright.sync_api import sync_playwright


STEEM_USERNAME = os.environ["STEEM_USERNAME"]

SEREY_LOGIN = os.environ.get(
    "SEREY_LOGIN",
    os.environ.get("SEREY_USERNAME", "")
).replace("@", "").strip()

SEREY_PASSWORD = os.environ.get(
    "SEREY_PASSWORD",
    ""
).strip()


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


DATA_FILE = "synced_posts.json"
TEMP_IMG_FILE = "temp_thumbnail.jpg"


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
                timeout=20
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
                f"RPC failed: {node} -> {e}",
                flush=True
            )

            time.sleep(1)

    raise RuntimeError(
        f"All Steem RPC nodes failed. "
        f"Last error: {last_error}"
    )


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

    except Exception as e:

        print(
            f"Could not read {DATA_FILE}: {e}",
            flush=True
        )

    return set()


def save_synced_posts(posts):

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


def extract_image_and_clean_body(
    body_text,
    json_metadata_str
):

    first_image_url = None


    try:

        meta = json.loads(
            json_metadata_str
        )

        if (
            isinstance(meta, dict)
            and
            isinstance(
                meta.get("image"),
                list
            )
            and
            meta["image"]
        ):

            first_image_url = (
                meta["image"][0]
            )

    except Exception:

        pass


    if not first_image_url:

        markdown_img = re.search(
            r'!\[[^\]]*\]\((https?://[^)\s]+)\)',
            body_text,
            re.IGNORECASE
        )

        if markdown_img:

            first_image_url = (
                markdown_img.group(1)
            )


    if not first_image_url:

        img_match = re.search(
            r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
            body_text,
            re.IGNORECASE
        )

        if img_match:

            first_image_url = (
                img_match.group(0)
            )


    clean_body = body_text


    clean_body = re.sub(
        r'!\[[^\]]*\]\([^)]+\)',
        '',
        clean_body
    )


    clean_body = re.sub(
        r'https?://[^\s<>"\']+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>"\']*)?',
        '',
        clean_body,
        flags=re.IGNORECASE
    )


    clean_body = re.sub(
        r'\n\s*\n\s*\n+',
        '\n\n',
        clean_body
    )


    clean_body = clean_body.strip()


    return first_image_url, clean_body


def get_recent_posts():

    print(
        f"\nFetching ALL historical posts "
        f"from Steemit: @{STEEM_USERNAME}",
        flush=True
    )


    all_posts = []

    seen_ids = set()

    start_author = None

    start_permlink = None

    page_number = 0


    while True:

        params = {
            "tag": STEEM_USERNAME,
            "limit": 100
        }


        if start_author and start_permlink:

            params["start_author"] = (
                start_author
            )

            params["start_permlink"] = (
                start_permlink
            )


        page_number += 1


        print(
            f"Fetching Steemit batch #{page_number}...",
            flush=True
        )


        result = steem_rpc(
            "condenser_api.get_discussions_by_blog",
            params
        )


        if not result:

            print(
                "No more Steemit results.",
                flush=True
            )

            break


        if start_author and start_permlink:

            batch = result[1:]

        else:

            batch = result


        if not batch:

            break


        added_this_batch = 0


        for post in batch:

            if post.get(
                "author"
            ) != STEEM_USERNAME:

                continue


            author = post.get(
                "author",
                ""
            )


            permlink = post.get(
                "permlink",
                ""
            )


            if not permlink:

                continue


            post_id = (
                f"{author}/{permlink}"
            )


            if post_id in seen_ids:

                continue


            seen_ids.add(
                post_id
            )


            raw_body = post.get(
                "body",
                ""
            )


            metadata = post.get(
                "json_metadata",
                "{}"
            )


            image_url, clean_body = (
                extract_image_and_clean_body(
                    raw_body,
                    metadata
                )
            )


            all_posts.append({

                "author": author,

                "permlink": permlink,

                "title": post.get(
                    "title",
                    ""
                ),

                "body": clean_body,

                "image": image_url,

                "category": post.get(
                    "category",
                    ""
                ),

                "created": post.get(
                    "created",
                    ""
                )

            })


            added_this_batch += 1


        print(
            f"Batch #{page_number}: "
            f"{len(result)} received, "
            f"{added_this_batch} new posts. "
            f"Total: {len(all_posts)}",
            flush=True
        )


        last_post = result[-1]


        new_start_author = last_post.get(
            "author"
        )


        new_start_permlink = last_post.get(
            "permlink"
        )


        if (
            new_start_author == start_author
            and
            new_start_permlink == start_permlink
        ):

            print(
                "Pagination boundary repeated. "
                "Stopping safely.",
                flush=True
            )

            break


        if added_this_batch == 0:

            print(
                "No new posts in this batch. "
                "Stopping safely.",
                flush=True
            )

            break


        start_author = (
            new_start_author
        )


        start_permlink = (
            new_start_permlink
        )


        if len(all_posts) >= 5000:

            print(
                "Reached 5000-post safety limit.",
                flush=True
            )

            break


        if len(result) < 100:

            print(
                "Last batch has fewer than "
                "100 results.",
                flush=True
            )

            break


        time.sleep(0.3)


    all_posts.reverse()


    print(
        f"\nTotal historical posts fetched: "
        f"{len(all_posts)}",
        flush=True
    )


    return all_posts


def download_image(image_url):

    if not image_url:

        return None


    try:

        print(
            f"Downloading image: {image_url}",
            flush=True
        )


        response = requests.get(
            image_url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )


        response.raise_for_status()


        content_type = response.headers.get(
            "content-type",
            ""
        ).lower()


        if "image" not in content_type:

            print(
                "URL did not return an image.",
                flush=True
            )

            return None


        with open(
            TEMP_IMG_FILE,
            "wb"
        ) as file:

            file.write(
                response.content
            )


        print(
            "Image downloaded successfully!",
            flush=True
        )


        return TEMP_IMG_FILE


    except Exception as e:

        print(
            f"Image download failed: {e}",
            flush=True
        )

        return None


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

        page.goto(
            "https://serey.io/blog/post/new",
            timeout=60000
        )


        page.wait_for_timeout(
            4000
        )


        title_box = page.locator(
            'input[placeholder*="title" i], '
            'input[placeholder*="Title"]'
        ).first


        title_box.fill(
            post["title"]
        )


        print(
            "  - Title filled!",
            flush=True
        )


        body_box = page.locator(
            'div[contenteditable="true"], '
            'textarea[placeholder*="content" i], '
            'textarea'
        ).first


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


        if post.get("image"):

            try:

                temp_image = download_image(
                    post["image"]
                )


                if temp_image:

                    file_input = page.locator(
                        'input[type="file"]'
                    ).first


                    if file_input.count() > 0:

                        file_input.set_input_files(
                            temp_image
                        )


                        print(
                            "  - Thumbnail image uploaded!",
                            flush=True
                        )


                        page.wait_for_timeout(
                            4000
                        )

                    else:

                        print(
                            "  - File input not found. "
                            "Continuing without image.",
                            flush=True
                        )


            except Exception as image_error:

                print(
                    f"  - Thumbnail upload skipped: "
                    f"{image_error}",
                    flush=True
                )


        page.locator(
            'button:has-text("Publish")'
        ).first.click(
            force=True
        )


        print(
            "  - First Publish button clicked!",
            flush=True
        )


        page.wait_for_timeout(
            6000
        )


        try:

            dropdown = page.locator(
                'div:has-text("Select category"), '
                '.ant-select, '
                'input[placeholder*="category" i]'
            ).first


            dropdown.click(
                force=True
            )


            page.wait_for_timeout(
                1500
            )


            option = page.locator(
                '.ant-select-item-option, '
                'div[title="Tech"], '
                'div[title="Crypto"], '
                'li'
            ).first


            if option.count() > 0:

                option.click(
                    force=True
                )

            else:

                page.keyboard.press(
                    "ArrowDown"
                )

                page.keyboard.press(
                    "Enter"
                )


            print(
                "  - Category selected!",
                flush=True
            )


        except Exception as category_error:

            print(
                "  - Category auto-selecting "
                "via keyboard...",
                flush=True
            )


            page.keyboard.press(
                "Tab"
            )


            page.keyboard.press(
                "ArrowDown"
            )


            page.keyboard.press(
                "Enter"
            )


        page.wait_for_timeout(
            2000
        )


        final_publish = page.locator(
            '.ant-modal-content button:has-text("Publish"), '
            '.ant-modal-footer button:has-text("Publish"), '
            'button:has-text("Publish")'
        ).last


        final_publish.click(
            force=True
        )


        print(
            "  - Final Publish button clicked!",
            flush=True
        )


        page.wait_for_timeout(
            10000
        )


        print(
            f"SUCCESSFULLY PUBLISHED ON SEREY: "
            f"{post['title']}",
            flush=True
        )


        return True


    except Exception as e:

        print(
            f"Failed to publish post on Serey: {e}",
            flush=True
        )


        return False


    finally:

        if os.path.exists(
            TEMP_IMG_FILE
        ):

            try:

                os.remove(
                    TEMP_IMG_FILE
                )

            except Exception:

                pass


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


    synced_posts = (
        load_synced_posts()
    )


    print(
        f"Previously synced posts: "
        f"{len(synced_posts)}",
        flush=True
    )


    posts = get_recent_posts()


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
        f"Total historical posts fetched: "
        f"{len(posts)}",
        flush=True
    )


    print(
        f"Unsynced posts available: "
        f"{len(new_posts)}",
        flush=True
    )


    # IMPORTANT:
    # Only ONE post per GitHub Actions run.

    new_posts_to_run = (
        new_posts[:1]
    )


    print(
        f"Publishing in this run "
        f"(Limit = 1): "
        f"{len(new_posts_to_run)}",
        flush=True
    )


    if not new_posts_to_run:

        print(
            "No new posts to sync!",
            flush=True
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


            page.locator(
                'a:has-text("Log in"), '
                'button:has-text("Log in"), '
                'a:has-text("Log In"), '
                'button:has-text("Log In")'
            ).first.click(
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


            page.locator(
                'input[placeholder="Username"], '
                'input[placeholder*="Username"]'
            ).first.fill(
                SEREY_LOGIN
            )


            page.locator(
                'input[placeholder="Private Key or Password"], '
                'input[placeholder*="Private Key"]'
            ).first.fill(
                SEREY_PASSWORD
            )


            page.locator(
                '.ant-modal-content button:has-text("Log in"), '
                '.ant-modal-content button:has-text("Log In"), '
                'button:has-text("Log in")'
            ).last.click(
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
                f"Login failed: {e}",
                flush=True
            )


            browser.close()

            return


        # ----------------------------------------------------
        # PUBLISH ONE POST
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
                    f"Saved as synced: "
                    f"{post_id}",
                    flush=True
                )


            else:

                print(
                    "Publishing failed. "
                    "Post was NOT saved "
                    "to synced_posts.json.",
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


if __name__ == "__main__":

    main()
