import os,json,re,time,requests
from playwright.sync_api import sync_playwright

USER=os.environ["STEEM_USERNAME"].strip()
LOGIN=os.environ.get("SEREY_LOGIN","").replace("@","").strip()
PASS=os.environ["SEREY_PASSWORD"].strip()

BASE="https://bengali.serey.io"
NEW=f"{BASE}/blog/post/new"
FILE="synced_posts.json"

NODES=[
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://api.moecki.online",
    "https://steem.619.io"
]

def rpc(method,params):
    for n in NODES:
        try:
            r=requests.post(n,json={
                "jsonrpc":"2.0","method":method,
                "params":params,"id":1
            },timeout=20)
            d=r.json()
            if "result" in d:return d["result"]
        except:pass
    raise Exception("Steem RPC failed")

def synced():
    try:
        return set(json.load(open(FILE,encoding="utf8")))
    except:return set()

def save(x):
    json.dump(sorted(x),open(FILE,"w",encoding="utf8"),
              ensure_ascii=False,indent=2)

def posts():
    out=[];seen=set()
    a=p=None

    while len(out)<5000:
        q={"tag":USER,"limit":100}
        if a:q.update(start_author=a,start_permlink=p)

        r=rpc("condenser_api.get_discussions_by_blog",q)
        if not r:break

        for x in (r[1:] if a else r):
            if x.get("author")!=USER:continue

            pid=f"{USER}/{x.get('permlink','')}"
            if pid in seen:continue
            seen.add(pid)

            body=x.get("body","")
            image=None

            try:
                m=json.loads(x.get("json_metadata","{}"))
                image=(m.get("image") or [None])[0]
            except:pass

            if not image:
                m=re.search(r'!\[[^\]]*\]\((https?://[^)]+)',body)
                if m:image=m.group(1)

            body=re.sub(r'!\[[^\]]*\]\([^)]+\)','',body).strip()

            out.append({
                "id":pid,
                "title":x.get("title","").strip(),
                "body":body,
                "image":image,
                "category":x.get("category","")
            })

        last=r[-1]
        na,np=last.get("author"),last.get("permlink")

        if (na,np)==(a,p):break
        a,p=na,np

        if len(r)<100:break

    return out[::-1]

def login(page):
    page.goto(BASE,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(3000)

    page.locator(
        'a:has-text("Log in"),button:has-text("Log in"),'
        'a:has-text("Log In"),button:has-text("Log In")'
    ).first.click(force=True)

    page.wait_for_timeout(2000)

    page.locator('input[placeholder*="Username"]').first.fill(LOGIN)
    page.locator('input[placeholder*="Private Key"]').first.fill(PASS)

    page.locator(
        'button:has-text("Log in"),button:has-text("Log In")'
    ).last.click(force=True)

    page.wait_for_timeout(5000)
    print("✓ SEREY LOGIN OK")

def image(url):
    if not url:return None
    try:
        r=requests.get(url,timeout=20,
                       headers={"User-Agent":"Mozilla/5.0"})
        if "image" not in r.headers.get("content-type",""):return None
        open("temp.jpg","wb").write(r.content)
        return "temp.jpg"
    except:return None

def publish(page,p):
    print("Publishing:",p["title"])

    page.goto(NEW,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(2500)

    page.locator('input[placeholder*="Title" i]').first.fill(p["title"])

    editor=page.locator('[contenteditable="true"]').first
    editor.click()
    editor.fill(p["body"])

    f=image(p["image"])
    if f:
        try:
            page.locator('input[type="file"]').first.set_input_files(f)
            page.wait_for_timeout(2500)
            print("✓ IMAGE")
        except:pass

    buttons=page.locator("button")
    pubs=[]

    for i in range(buttons.count()):
        b=buttons.nth(i)
        try:
            if b.is_visible() and b.inner_text().strip().lower()=="publish":
                pubs.append(b)
        except:pass

    if not pubs:return False

    pubs[-1].click(force=True)
    print("✓ FIRST PUBLISH")

    page.wait_for_timeout(2500)

    # Category if available
    try:
        page.get_by_text("Select category",exact=True).first.click(force=True)
        page.wait_for_timeout(500)
        page.get_by_text(p["category"],exact=True).last.click(force=True)
    except:pass

    # Final publish
    buttons=page.locator("button")
    final=None

    for i in range(buttons.count()):
        b=buttons.nth(i)
        try:
            if b.is_visible() and b.inner_text().strip().lower()=="publish":
                final=b
        except:pass

    if not final:return False

    final.click(force=True)
    print("✓ FINAL PUBLISH")

    # Must become /authors/mamun/...
    for _ in range(10):
        page.wait_for_timeout(3000)
        url=page.url

        print("URL:",url)

        if re.match(
            r"https://bengali\.serey\.io/authors/[^/]+/[^/?#]+",
            url
        ):
            print("✓ PUBLISHED:",url)
            return True

    print("❌ NOT PUBLISHED")
    print(page.locator("body").inner_text()[:3000])

    return False

def main():
    print("="*50)
    print("STEEM → SEREY AUTO SYNC")
    print("="*50)

    done=synced()
    ps=posts()

    new=[p for p in ps if p["id"] not in done]

    print("Total posts:",len(ps))
    print("Previously synced:",len(done))
    print("Unsynced:",len(new))

    if not new:
        print("Nothing to publish.")
        return

    p=new[0]

    with sync_playwright() as x:
        browser=x.chromium.launch(headless=True)
        page=browser.new_page(
            viewport={"width":1280,"height":900}
        )

        try:
            login(page)

            if publish(page,p):
                done.add(p["id"])
                save(done)
                print("✓ SAVED:",p["id"])
            else:
                print("⚠ NOT SAVED")

        finally:
            browser.close()

    print("DONE")

if __name__=="__main__":
    main()
