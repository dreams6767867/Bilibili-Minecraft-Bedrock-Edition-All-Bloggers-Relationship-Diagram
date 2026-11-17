# -*- coding: utf-8 -*-
"""验证B站接口链路: spi -> nav(wbi) -> 搜索 -> 视频详情"""
import json, time, hashlib, urllib.request, urllib.parse, http.cookiejar, sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [("User-Agent", UA), ("Referer", "https://www.bilibili.com/"),
                     ("Accept", "application/json, text/plain, */*"),
                     ("Accept-Language", "zh-CN,zh;q=0.9")]

def get(url, timeout=15):
    with opener.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

MIXIN_TAB = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]

def mixin_key(img, sub):
    raw = img.rsplit("/",1)[-1].split(".")[0] + sub.rsplit("/",1)[-1].split(".")[0]
    return "".join(raw[i] for i in MIXIN_TAB)[:32]

def wbi_sign(params, img, sub):
    key = mixin_key(img, sub)
    params = dict(params, wts=int(time.time()))
    items = sorted(params.items())
    q = urllib.parse.urlencode(items, quote_via=urllib.parse.quote)
    q = "".join(c for c in q if c not in "!'()*")
    params["w_rid"] = hashlib.md5((q + key).encode()).hexdigest()
    return urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)

def main():
    spi = get("https://api.bilibili.com/x/frontend/finger/spi")
    print("spi code:", spi.get("code"))
    b3 = spi["data"]["b_3"]; b4 = spi["data"]["b_4"]
    # 把 buvid 写进 cookie
    for name, val, dom in [("buvid3", b3, ".bilibili.com"), ("buvid4", b4, ".bilibili.com"),
                           ("b_nut", str(int(time.time())), ".bilibili.com")]:
        ck = http.cookiejar.Cookie(0, name, val, None, False, dom, True, False, "/", True,
                                   False, int(time.time())+86400*30, False, None, None, {})
        cj.set_cookie(ck)
    nav = get("https://api.bilibili.com/x/web-interface/nav")
    print("nav code:", nav.get("code"), "(未登录-101属正常)")
    wbi = nav["data"]["wbi_img"]
    img, sub = wbi["img_url"], wbi["sub_url"]
    print("wbi keys ok:", img.rsplit('/',1)[-1][:12], sub.rsplit('/',1)[-1][:12])

    q = wbi_sign({"search_type": "video", "keyword": "我的世界基岩版", "page": 1,
                  "order": "totalrank", "page_size": 30}, img, sub)
    s = get("https://api.bilibili.com/x/web-interface/wbi/search/type?" + q)
    print("search code:", s.get("code"), s.get("message"))
    if s.get("code") != 0:
        print(json.dumps(s, ensure_ascii=False)[:500]); return
    res = s["data"].get("result") or []
    print("numResults:", s["data"].get("numResults"), "numPages:", s["data"].get("numPages"), "本页:", len(res))
    if not res:
        print("无结果"); return
    v = res[0]
    print("样例视频:", v.get("bvid"), "|", v.get("author"), "| mid:", v.get("mid"), "|", v.get("title")[:40])
    time.sleep(1)
    d = get("https://api.bilibili.com/x/web-interface/view?bvid=" + v["bvid"])
    print("view code:", d.get("code"))
    if d.get("code") == 0:
        dd = d["data"]
        print("owner:", dd["owner"]["name"], "| staff:", [(x["mid"], x["name"]) for x in dd.get("staff", [])])
        print("desc前80:", (dd.get("desc") or "")[:80].replace("\n", " "))
        print("is_cooperation:", dd.get("rights", {}).get("is_cooperation"))
    # 保存 buvid 供爬虫复用
    with open("buvid.json", "w", encoding="utf-8") as f:
        json.dump({"buvid3": b3, "buvid4": b4}, f)
    print("OK buvid 已存 buvid.json")

if __name__ == "__main__":
    main()