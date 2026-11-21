# -*- coding: utf-8 -*-
"""B站基岩版创作者合作图爬虫
用法: python crawl.py search   # 阶段1: 关键词×年份切片搜索
      python crawl.py details  # 阶段2: 视频详情(联合投稿/简介/头像)
状态全部落盘 state/, 可随时中断续跑。
"""
import json, os, sys, time, random, re, hashlib, calendar, collections, urllib.request, urllib.parse, urllib.error, http.cookiejar

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state")
os.makedirs(STATE, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

KEYWORDS = ["我的世界基岩版", "基岩版", "我的世界PE", "MCPE", "我的世界手机版",
            "我的世界携带版", "我的世界手游", "我的世界addon", "基岩版行为包", "minecraft bedrock", "MCBE"]
YEARS = list(range(2011, 2027))  # 每年一个切片, 绕过单查询1000条上限; 携带版诞生于2011-08-06
ERA_SPLIT = calendar.timegm((2017, 9, 20, 0, 0, 0)) - 8 * 3600  # 基岩版名称启用日

def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    print(line, flush=True)
    with open(os.path.join(STATE, "crawl.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load(name, default):
    p = os.path.join(STATE, name + ".json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default

def save(name, obj):
    p = os.path.join(STATE, name + ".json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)

class RiskError(Exception):
    """HTTP层风控(412/403), 必须走全局刹车而不是普通网络重试"""
    def __init__(self, status):
        Exception.__init__(self, "http %d" % status)
        self.status = status

MIXIN_TAB = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]

class Bili:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", UA), ("Referer", "https://search.bilibili.com/"),
                                  ("Accept", "application/json, text/plain, */*"),
                                  ("Accept-Language", "zh-CN,zh;q=0.9"),
                                  ("Origin", "https://search.bilibili.com")]
        self.img = self.sub = None
        self.keys_ts = 0
        self.refresh_buvid()

    def cookie(self, name, val):
        ck = http.cookiejar.Cookie(0, name, val, None, False, ".bilibili.com", True, False, "/", True,
                                   False, int(time.time()) + 86400 * 30, False, None, None, {})
        self.cj.set_cookie(ck)

    def refresh_buvid(self):
        try:
            with self.opener.open("https://api.bilibili.com/x/frontend/finger/spi", timeout=15) as r:
                d = json.loads(r.read().decode())["data"]
            self.cookie("buvid3", d["b_3"]); self.cookie("buvid4", d["b_4"])
            self.cookie("b_nut", str(int(time.time())))
        except Exception as e:
            log("spi失败: %r" % e)

    def get(self, url, timeout=15):
        try:
            with self.opener.open(url, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (412, 403):
                raise RiskError(e.code)
            raise

    def refresh_keys(self):
        if self.img and time.time() - self.keys_ts < 1800:
            return
        d = self.get("https://api.bilibili.com/x/web-interface/nav")
        w = d["data"]["wbi_img"]
        self.img, self.sub = w["img_url"], w["sub_url"]
        self.keys_ts = time.time()

    def wbi_qs(self, params):
        self.refresh_keys()
        raw = self.img.rsplit("/", 1)[-1].split(".")[0] + self.sub.rsplit("/", 1)[-1].split(".")[0]
        key = "".join(raw[i] for i in MIXIN_TAB)[:32]
        p = dict(params, wts=int(time.time()))
        q = "".join(c for c in urllib.parse.urlencode(sorted(p.items()), quote_via=urllib.parse.quote) if c not in "!'()*")
        p["w_rid"] = hashlib.md5((q + key).encode()).hexdigest()
        return urllib.parse.urlencode(sorted(p.items()), quote_via=urllib.parse.quote)

    def signed_get(self, path, params):
        return self.get("https://api.bilibili.com/x/web-interface/wbi/" + path + "?" + self.wbi_qs(params))

    def call(self, fn, what, tries=4, on_risk=None):
        """带风控退避的调用: HTTP412/403 或 code -412/-352 时全局刹车+换buvid重试"""
        for i in range(tries):
            try:
                d = fn()
                code = d.get("code")
                if code == 0:
                    return d
                if code in (-412, -352, -799):
                    if on_risk:
                        on_risk(code)
                    wait = 60 * (i + 1) + random.uniform(0, 15)
                    log("风控 %s code=%s, 休眠%.0fs (%d/%d)" % (what, code, wait, i + 1, tries))
                    time.sleep(wait)
                    self.refresh_buvid()
                    self.img = None
                    continue
                if code == -403:
                    self.img = None
                    time.sleep(5)
                    continue
                log("接口错误 %s code=%s msg=%s" % (what, code, d.get("message")))
                return d
            except RiskError as e:
                if on_risk:
                    on_risk(e.status)
                wait = 45 * (i + 1) + random.uniform(0, 15)
                log("风控 %s HTTP%d, 休眠%.0fs (%d/%d)" % (what, e.status, wait, i + 1, tries))
                time.sleep(wait)
                try:
                    self.refresh_buvid()
                except Exception:
                    pass
                self.img = None
            except Exception as e:
                log("网络异常 %s: %r, 10s后重试" % (what, e))
                time.sleep(10)
        return None

def year_range(y):
    beg = calendar.timegm((y, 1, 1, 0, 0, 0)) - 8 * 3600
    if y == 2011:
        beg = calendar.timegm((2011, 8, 6, 0, 0, 0)) - 8 * 3600
    end = calendar.timegm((y + 1, 1, 1, 0, 0, 0)) - 8 * 3600
    return beg, end

def phase_search():
    bili = Bili()
    videos = load("search_videos", {})     # bvid -> 搜索条目
    creators = load("creators", {})        # mid -> {name, kws:[], n}
    done = set(load("search_done", []))    # "kw|slice|order|page"
    # 任务: 每关键词×每年切片(totalrank) + 每关键词全量(pubdate最新/click最热)
    tasks = []
    for kw in KEYWORDS:
        for y in YEARS:
            tasks.append((kw, str(y), "totalrank"))
        tasks.append((kw, "all", "pubdate"))
        tasks.append((kw, "all", "click"))
    log("搜索任务 %d 组, 已完成 %d 页, 已有视频 %d, UP主 %d" % (len(tasks), len(done), len(videos), len(creators)))
    req = 0
    for kw, sl, order in tasks:
        if "%s|%s|%s|END" % (kw, sl, order) in done:
            continue
        page = 1
        while page <= 50:
            tag = "%s|%s|%s|%d" % (kw, sl, order, page)
            if tag in done:
                page += 1
                continue
            params = {"search_type": "video", "keyword": kw, "page": page, "page_size": 30, "order": order}
            if sl != "all":
                beg, end = year_range(int(sl))
                params["pubtime_begin_s"] = beg
                params["pubtime_end_s"] = end
            d = bili.call(lambda: bili.signed_get("search/type", params), "搜索 %s %s %s p%d" % (kw, sl, order, page))
            req += 1
            if d is None or d.get("code") != 0:
                log("跳过 %s" % tag)
                done.add(tag)  # 失败的页标记跳过, 避免卡死; 之后可清done重抓
                save("search_done", sorted(done))
                break
            data = d["data"]
            res = data.get("result") or []
            nump = data.get("numPages") or 0
            for v in res:
                bv = v.get("bvid")
                if not bv:
                    continue
                if bv not in videos:
                    videos[bv] = {"mid": str(v.get("mid")), "author": v.get("author") or "",
                                  "title": (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", ""),
                                  "desc": v.get("description") or "", "pubdate": v.get("pubdate") or 0,
                                  "tag": v.get("tag") or "", "kw": kw}
                mid = str(v.get("mid"))
                c = creators.setdefault(mid, {"name": v.get("author") or "", "kws": [], "n": 0})
                c["n"] += 1
                if kw not in c["kws"]:
                    c["kws"].append(kw)
                if v.get("author"):
                    c["name"] = v["author"]
            done.add(tag)
            if req % 10 == 0:
                save("search_videos", videos); save("creators", creators); save("search_done", sorted(done))
                log("进度: 请求%d 视频%d UP%d | %s %s %s p%d/%d 本页%d" % (req, len(videos), len(creators), kw, sl, order, page, nump, len(res)))
            if not res or page >= nump:
                done.add("%s|%s|%s|END" % (kw, sl, order))
                save("search_done", sorted(done))
                break
            page += 1
            time.sleep(random.uniform(1.1, 1.9))
        time.sleep(random.uniform(0.4, 0.9))
    save("search_videos", videos); save("creators", creators); save("search_done", sorted(done))
    log("搜索阶段完成: 视频 %d, UP主 %d, 请求 %d" % (len(videos), len(creators), req))

SPACE_PAGES_MAX = 5  # 每人最多5页(150条), 防超大UP拖垮整轮

def phase_space():
    """按创作者名字反查投稿(搜索接口枚举), 补回关键词排名漏掉的基岩视频"""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from build_graph import bedrock_hit
    videos = load("search_videos", {})
    details = load("details", {})
    creators = load("creators", {})
    hit = {bv for bv, v in videos.items() if bedrock_hit(v["title"], v["desc"], v.get("tag", ""))}
    mids = set()
    for bv in hit:
        v = videos[bv]
        if v.get("mid") and v["mid"] != "0":
            mids.add(str(v["mid"]))
        d = details.get(bv) or {}
        for s in d.get("staff", []):
            if s.get("mid") and s["mid"] != "0":
                mids.add(str(s["mid"]))
    name2mids = {}
    for m in mids:
        nm = (creators.get(m) or {}).get("name") or ""
        if nm:
            name2mids.setdefault(nm, set()).add(m)
    space_videos = load("space_videos", {})
    done = set(load("space_done", []))   # 按名字记录, 可断点续跑
    todo = [nm for nm in sorted(name2mids) if nm not in done]
    log("名字枚举: 创作者 %d (名字 %d), 已完成 %d, 本轮 %d, 已有候选 %d"
        % (len(mids), len(name2mids), len(done), len(todo), len(space_videos)))
    if not todo:
        log("名字枚举无需进行")
        return
    lock = threading.Lock()
    pause_until = [0.0]
    delay_floor = [1.8]
    tls = threading.local()
    counter = [0]
    added_cand = [len(space_videos)]
    failed = []

    def brake(code):
        with lock:
            pause_until[0] = max(pause_until[0], time.time() + 240)
            delay_floor[0] = min(8.0, delay_floor[0] * 2.0)
            log("风控刹车 code=%s: 全局暂停240s, delay_floor=%.1fs" % (code, delay_floor[0]))

    probe = Bili()
    while True:
        wait = 90
        try:
            d = probe.signed_get("search/type", {"search_type": "video", "keyword": "我的世界基岩版",
                                                 "page": 1, "page_size": 30, "order": "pubdate"})
            if d.get("code") == 0:
                log("搜索接口探测通过, 开始名字枚举")
                break
            log("搜索端口 code=%s, 90s后重探" % d.get("code"))
        except RiskError as e:
            log("搜索接口冷却(HTTP%d), 120s后重探" % e.status)
            wait = 120
        except Exception as e:
            log("探测异常 %r, 90s后重试" % e)
        time.sleep(wait)

    def worker(name):
        while time.time() < pause_until[0]:
            time.sleep(2)
        if not hasattr(tls, "bili"):
            tls.bili = Bili()
        bili = tls.bili
        want = name2mids[name]
        pn = 1
        max_pn = 1
        ok = True
        while pn <= min(SPACE_PAGES_MAX, max_pn):
            params = {"search_type": "video", "keyword": name, "page": pn, "page_size": 30, "order": "pubdate"}
            d = bili.call(lambda: bili.signed_get("search/type", params), "枚举 " + name, tries=3, on_risk=brake)
            if d is None or d.get("code") != 0:
                ok = False
                with lock:
                    log("枚举失败 %s code=%s (下轮重试)" % (name, (d or {}).get("code", "net")))
                break
            data = d["data"] or {}
            res = data.get("result") or []
            max_pn = data.get("numPages") or 1
            with lock:
                inserted = 0
                for v in res:
                    mid = str(v.get("mid"))
                    if mid not in want:
                        continue
                    bv = v.get("bvid")
                    if not bv:
                        continue
                    title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                    desc = v.get("description") or ""
                    tag = v.get("tag") or ""
                    if not bedrock_hit(title, desc, tag):
                        continue
                    if bv not in space_videos:
                        space_videos[bv] = {"mid": mid, "author": v.get("author") or name,
                                            "title": title, "desc": desc,
                                            "pubdate": v.get("pubdate") or 0, "tag": tag, "union": 0}
                        inserted += 1
                added_cand[0] += inserted
            if not res or pn >= max_pn:
                break
            pn += 1
            time.sleep(random.uniform(delay_floor[0], delay_floor[0] + 0.4))
        with lock:
            counter[0] += 1
            if ok:
                done.add(name)
            else:
                failed.append(name)
            if counter[0] % 200 == 0:
                save("space_videos", space_videos)
                save("space_done", sorted(done))
                log("枚举进度 %d/%d (%.1f%%), 候选 %d, delay_floor=%.1fs"
                    % (counter[0], len(todo), 100.0 * counter[0] / max(1, len(todo)), added_cand[0], delay_floor[0]))
                if delay_floor[0] > 1.8 and time.time() > pause_until[0]:
                    delay_floor[0] = max(1.8, delay_floor[0] * 0.9)
        time.sleep(random.uniform(0.3, 0.7))

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(worker, todo))
    save("space_videos", space_videos)
    save("space_done", sorted(done))
    if failed:
        log("本轮失败 %d 个名字, 保留待下轮重试: %s" % (len(failed), ", ".join(failed[:8])))
    added = 0
    for bv, rec in space_videos.items():
        if bv not in videos:
            videos[bv] = {"mid": rec["mid"], "author": rec["author"], "title": rec["title"],
                          "desc": rec["desc"], "pubdate": rec["pubdate"], "tag": rec.get("tag", ""),
                          "kw": "名字枚举"}
            added += 1
    save("search_videos", videos)
    log("名字枚举完成: 扫描 %d 个名字, 候选视频 %d (新增并入 %d)" % (len(todo), len(space_videos), added))

def phase_mcbe_months():
    """MCBE按月切片搜索, 补回年度1000条上限漏掉的纯MCBE视频"""
    from build_graph import bedrock_hit
    bili = Bili()
    videos = load("search_videos", {})
    done = set(load("mcbe_months_done", []))
    tasks = []
    now = time.time()
    for y in range(2011, 2027):
        for m in range(1, 13):
            if y == 2011 and m < 8:
                continue
            beg = calendar.timegm((y, m, 1, 0, 0, 0)) - 8 * 3600
            if beg > now:
                continue
            end = calendar.timegm((y + 1, 1, 1, 0, 0, 0)) - 8 * 3600 if m == 12 \
                else calendar.timegm((y, m + 1, 1, 0, 0, 0)) - 8 * 3600
            tasks.append((y, m, beg, end))
    log("MCBE月切片: 任务 %d 个月, 已完成 %d, 已有视频 %d" % (len(tasks), len(done), len(videos)))
    req = 0; added = 0
    for y, m, beg, end in tasks:
        tag = "%d-%02d" % (y, m)
        if tag in done:
            continue
        page = 1; nump = 0
        while page <= 34:
            params = {"search_type": "video", "keyword": "MCBE", "page": page, "page_size": 30,
                      "order": "pubdate", "pubtime_begin_s": beg, "pubtime_end_s": end}
            d = bili.call(lambda: bili.signed_get("search/type", params), "MCBE %s p%d" % (tag, page))
            req += 1
            if d is None or d.get("code") != 0:
                log("MCBE月 %s p%d 失败, 跳过" % (tag, page))
                break
            data = d["data"]; res = data.get("result") or []; nump = data.get("numPages") or 0
            for v in res:
                bv = v.get("bvid")
                if not bv or bv in videos:
                    continue
                title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                desc = v.get("description") or ""; tg = v.get("tag") or ""
                if not bedrock_hit(title, desc, tg):
                    continue
                videos[bv] = {"mid": str(v.get("mid")), "author": v.get("author") or "", "title": title,
                              "desc": desc, "pubdate": v.get("pubdate") or 0, "tag": tg, "kw": "MCBE月切"}
                added += 1
            if not res or page >= nump:
                break
            page += 1
            time.sleep(random.uniform(1.0, 1.6))
        done.add(tag)
        if req % 10 == 0:
            save("search_videos", videos); save("mcbe_months_done", sorted(done))
            log("MCBE月切片 请求%d 新增%d | %s p%d/%d" % (req, added, tag, page, nump))
        time.sleep(random.uniform(0.3, 0.6))
    save("search_videos", videos); save("mcbe_months_done", sorted(done))
    log("MCBE月切片完成: 请求 %d, 新增视频 %d" % (req, added))

def phase_big():
    """头部创作者(已知视频>=150)名字枚举上限从150抬到300重扫"""
    from build_graph import bedrock_hit
    videos = load("search_videos", {})
    creators = load("creators", {})
    cnt = collections.Counter(r["mid"] for r in videos.values())
    targets = sorted([m for m, c in cnt.items() if c >= 150], key=lambda m: -cnt[m])
    log("大号重扫: 目标 %d 人 (已知视频>=150)" % len(targets))
    bili = Bili()
    added = 0
    for k, mid in enumerate(targets, 1):
        name = (creators.get(mid) or {}).get("name") or ""
        if not name:
            log("跳过无名 %s" % mid)
            continue
        pn = 1; nump = 1
        while pn <= min(10, nump):
            params = {"search_type": "video", "keyword": name, "page": pn, "page_size": 30, "order": "pubdate"}
            d = bili.call(lambda: bili.signed_get("search/type", params), "大号 " + name, tries=3)
            if d is None or d.get("code") != 0:
                log("大号失败 %s p%d" % (name, pn))
                break
            data = d["data"] or {}
            res = data.get("result") or []
            nump = data.get("numPages") or 1
            for v in res:
                if str(v.get("mid")) != mid:
                    continue
                bv = v.get("bvid")
                if not bv or bv in videos:
                    continue
                title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                desc = v.get("description") or ""; tag = v.get("tag") or ""
                if not bedrock_hit(title, desc, tag):
                    continue
                videos[bv] = {"mid": mid, "author": v.get("author") or name, "title": title,
                              "desc": desc, "pubdate": v.get("pubdate") or 0, "tag": tag, "kw": "大号重扫"}
                added += 1
            if not res or pn >= nump:
                break
            pn += 1
            time.sleep(random.uniform(1.0, 1.5))
        if k % 5 == 0:
            save("search_videos", videos)
            log("大号进度 %d/%d, 新增 %d" % (k, len(targets), added))
        time.sleep(random.uniform(0.4, 0.8))
    save("search_videos", videos)
    log("大号重扫完成: %d 人, 新增视频 %d, 总视频 %d" % (len(targets), added, len(videos)))

def phase_week():
    """对单月结果超过1000条(被截断)的月份按周切片重扫, 突破1000条上限"""
    from build_graph import bedrock_hit
    census = load("census_months", {})
    videos = load("search_videos", {})
    done = set(load("week_done", []))
    tasks = []
    for kw, months in census.items():
        for key, val in months.items():
            if (val.get("total") or 0) < 1000:
                continue
            y, m = [int(x) for x in key.split("-")]
            beg = calendar.timegm((y, m, 1, 0, 0, 0)) - 8 * 3600
            nxt = (y + 1, 1) if m == 12 else (y, m + 1)
            end = calendar.timegm((nxt[0], nxt[1], 1, 0, 0, 0)) - 8 * 3600
            t = beg
            while t < end:
                tasks.append((kw, key, t, min(t + 7 * 86400, end)))
                t += 7 * 86400
    log("周切片: 关键词 %s, 切片任务 %d, 已完成 %d, 已有视频 %d"
        % ("/".join(census.keys()), len(tasks), len(done), len(videos)))
    bili = Bili()
    req = 0; added = 0
    for kw, key, beg, end in tasks:
        tag = "%s|%s|%d" % (kw, key, beg)
        if tag in done:
            continue
        page = 1; nump = 1
        while page <= min(34, nump):
            params = {"search_type": "video", "keyword": kw, "page": page, "page_size": 30,
                      "order": "pubdate", "pubtime_begin_s": beg, "pubtime_end_s": end}
            d = bili.call(lambda: bili.signed_get("search/type", params), "周切 %s %s p%d" % (kw, key, page))
            req += 1
            if d is None or d.get("code") != 0:
                log("周切失败 %s %s p%d" % (kw, key, page))
                break
            data = d["data"]; res = data.get("result") or []; nump = data.get("numPages") or 0
            for v in res:
                bv = v.get("bvid")
                if not bv or bv in videos:
                    continue
                title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                desc = v.get("description") or ""; tg = v.get("tag") or ""
                if not bedrock_hit(title, desc, tg):
                    continue
                videos[bv] = {"mid": str(v.get("mid")), "author": v.get("author") or "", "title": title,
                              "desc": desc, "pubdate": v.get("pubdate") or 0, "tag": tg, "kw": "周切"}
                added += 1
            if not res or page >= nump:
                break
            page += 1
            time.sleep(random.uniform(0.9, 1.3))
        done.add(tag)
        if req % 10 == 0:
            save("search_videos", videos); save("week_done", sorted(done))
            log("周切进度 请求%d 新增%d | %s %s p%d/%d" % (req, added, kw, key, page, nump))
        time.sleep(random.uniform(0.3, 0.6))
    save("search_videos", videos); save("week_done", sorted(done))
    log("周切片完成: 请求 %d, 新增视频 %d, 总视频 %d" % (req, added, len(videos)))

def phase_union():
    """遍历全部创作者最新30条, 用 is_union_video 标记找联合投稿(不限基岩标签)"""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    with open(os.path.join(BASE, "graph.json"), encoding="utf-8") as f:
        g = json.load(f)
    creators = load("creators", {})
    faces = load("faces", {})
    mids = [str(n["id"]) for n in g["nodes"]]
    uv = load("union_videos", {})
    done = set(load("union_done", []))
    # 旧格式(裸mid=只扫过第1页)迁移为 mid|1
    bare = [m for m in done if "|" not in m]
    for m in bare:
        done.discard(m)
        done.add("%s|1" % m)
    # staff-only 创作者在 creators.json 无名字: 用 faces.json 补齐
    def name_of(mid):
        return (((creators.get(mid) or {}).get("name")) or ((faces.get(mid) or {}).get("name")) or "")
    PAGES = 3
    def missing(m):
        return any("%s|%d" % (m, p) not in done for p in range(1, PAGES + 1))
    todo = [m for m in mids if missing(m)]
    log("联合投稿扫描: 创作者 %d, 已完成 %d, 本轮 %d, 已有联合视频 %d (每人最多%d页)"
        % (len(mids), len(mids) - len(todo), len(todo), len(uv), PAGES))
    if not todo:
        log("联合投稿扫描无需进行")
        return
    lock = threading.Lock()
    pause_until = [0.0]
    delay_floor = [0.9]
    tls = threading.local()
    counter = [0]
    found = [0]

    def brake(code):
        with lock:
            pause_until[0] = max(pause_until[0], time.time() + 180)
            delay_floor[0] = min(6.0, delay_floor[0] * 1.8)
            log("风控刹车 code=%s: 暂停180s delay_floor=%.1fs" % (code, delay_floor[0]))

    def worker(mid):
        while time.time() < pause_until[0]:
            time.sleep(2)
        if not hasattr(tls, "bili"):
            tls.bili = Bili()
        bili = tls.bili
        name = name_of(mid)
        if not name:
            with lock:
                for p in range(1, PAGES + 1):
                    done.add("%s|%d" % (mid, p))
                counter[0] += 1
            return
        pn = 1
        nump = PAGES
        while pn <= min(PAGES, nump):
            key = "%s|%d" % (mid, pn)
            if key in done:
                pn += 1
                continue
            params = {"search_type": "video", "keyword": name, "page": pn, "page_size": 30, "order": "pubdate"}
            d = bili.call(lambda: bili.signed_get("search/type", params), "联合 %s p%d" % (name, pn), tries=3, on_risk=brake)
            if d and d.get("code") == 0:
                data = d.get("data") or {}
                rs = data.get("result") or []
                nump = data.get("numPages") or 1
                with lock:
                    for v in rs:
                        if str(v.get("mid")) != mid or not v.get("is_union_video"):
                            continue
                        bv = v.get("bvid")
                        if not bv or bv in uv:
                            continue
                        title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                        uv[bv] = {"mid": mid, "author": v.get("author") or name, "title": title,
                                  "desc": v.get("description") or "", "pubdate": v.get("pubdate") or 0,
                                  "tag": v.get("tag") or "", "union": 1}
                        found[0] += 1
                    done.add(key)
                    if not rs or pn >= nump:
                        for k in range(pn + 1, PAGES + 1):
                            done.add("%s|%d" % (mid, k))
            else:
                with lock:
                    log("联合失败 %s p%d code=%s" % (name, pn, (d or {}).get("code", "net")))
            pn += 1
            time.sleep(random.uniform(delay_floor[0], delay_floor[0] + 0.4))
        with lock:
            counter[0] += 1
            if counter[0] % 200 == 0:
                save("union_videos", uv); save("union_done", sorted(done))
                log("联合扫描进度 %d/%d (%.1f%%), 命中 %d, delay_floor=%.1fs"
                    % (counter[0], len(todo), 100.0 * counter[0] / max(1, len(todo)), found[0], delay_floor[0]))
                if delay_floor[0] > 0.9 and time.time() > pause_until[0]:
                    delay_floor[0] = max(0.9, delay_floor[0] * 0.9)
        time.sleep(random.uniform(0.2, 0.5))

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(worker, todo))
    save("union_videos", uv); save("union_done", sorted(done))
    videos = load("search_videos", {})
    added = 0
    for bv, rec in uv.items():
        if bv not in videos:
            videos[bv] = {"mid": rec["mid"], "author": rec["author"], "title": rec["title"],
                          "desc": rec["desc"], "pubdate": rec["pubdate"], "tag": rec.get("tag", ""),
                          "union": 1, "kw": "联合扫描"}
            added += 1
        else:
            videos[bv]["union"] = 1
    save("search_videos", videos)
    log("联合投稿扫描完成: %d 条联合视频 (新并入搜索集 %d)" % (len(uv), added))

MC_RE = re.compile(r"我的世界|minecraft|(?<![A-Za-z])mc(?![A-Za-z])|mcbe|mcpe|基岩|bedrock", re.I)

def phase_staffmc():
    """核查无基岩视频的联合投稿参与者: 自己是否有我的世界类视频"""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    with open(os.path.join(BASE, "graph.json"), encoding="utf-8") as f:
        g = json.load(f)
    creators = load("creators", {})
    faces = load("faces", {})
    uv = load("union_videos", {})
    uvset = set(uv)
    targets = [str(n["id"]) for n in g["nodes"] if (n.get("vpe", 0) + n.get("vbr", 0)) == 0]
    info = load("staff_mc", {})
    done = set(load("staff_mc_done", []))
    todo = [m for m in targets if m not in done]
    log("参与者核查: 无视频节点 %d, 已完成 %d, 本轮 %d" % (len(targets), len(done), len(todo)))
    if not todo:
        return
    lock = threading.Lock()
    pause_until = [0.0]
    delay_floor = [0.9]
    tls = threading.local()
    counter = [0]

    def name_of(mid):
        return (((creators.get(mid) or {}).get("name")) or ((faces.get(mid) or {}).get("name")) or "")

    def brake(code):
        with lock:
            pause_until[0] = max(pause_until[0], time.time() + 180)
            delay_floor[0] = min(6.0, delay_floor[0] * 1.8)
            log("风控刹车 code=%s: 暂停180s delay_floor=%.1fs" % (code, delay_floor[0]))

    def worker(mid):
        while time.time() < pause_until[0]:
            time.sleep(2)
        if not hasattr(tls, "bili"):
            tls.bili = Bili()
        bili = tls.bili
        name = name_of(mid)
        if not name:
            with lock:
                info[mid] = {"mc": 0, "other": 0, "none": 1}
                done.add(mid); counter[0] += 1
            return
        params = {"search_type": "video", "keyword": name, "page": 1, "page_size": 30, "order": "pubdate"}
        d = bili.call(lambda: bili.signed_get("search/type", params), "参与者 " + name, tries=3, on_risk=brake)
        if d and d.get("code") == 0:
            rs = ((d.get("data") or {}).get("result")) or []
            mc = other = 0
            for v in rs:
                if str(v.get("mid")) != mid:
                    continue
                if v.get("bvid") in uvset:
                    continue
                other += 1
                text = (v.get("title") or "") + " " + (v.get("tag") or "") + " " + (v.get("description") or "")
                if MC_RE.search(text):
                    mc += 1
            with lock:
                info[mid] = {"mc": mc, "other": other}
                done.add(mid); counter[0] += 1
                if counter[0] % 200 == 0:
                    save("staff_mc", info); save("staff_mc_done", sorted(done))
                    log("参与者核查进度 %d/%d, delay_floor=%.1fs"
                        % (counter[0], len(todo), delay_floor[0]))
                    if delay_floor[0] > 0.9 and time.time() > pause_until[0]:
                        delay_floor[0] = max(0.9, delay_floor[0] * 0.9)
        else:
            with lock:
                log("参与者核查失败 %s code=%s" % (name, (d or {}).get("code", "net")))
        time.sleep(random.uniform(delay_floor[0], delay_floor[0] + 0.4))

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(worker, todo))
    save("staff_mc", info); save("staff_mc_done", sorted(done))
    keep = sum(1 for m, v in info.items() if v.get("mc", 0) >= 1 or v.get("other", 0) <= 1)
    log("参与者核查完成: %d 人, 符合'有MC视频或只有此联投' %d 人" % (len(info), keep))

def phase_details():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from build_graph import bedrock_hit
    videos = load("search_videos", {})
    details = load("details", {})   # bvid -> {owner, staff, desc, title, pubdate}
    faces = load("faces", {})       # mid -> {name, face}
    bad = [bv for bv, v in details.items() if isinstance(v, dict) and "err" in v]
    for bv in bad:
        del details[bv]
    if bad:
        save("details", details)
        log("清除上轮失败记录 %d 条, 本轮重抓" % len(bad))
    # 只抓基岩命中视频 + 基岩UP主标题含合作信号的视频, 跳过模糊匹配噪声
    hit = {bv for bv, v in videos.items()
           if bedrock_hit(v["title"], v["desc"], v.get("tag", ""))}
    ok_authors = {videos[bv]["mid"] for bv in hit}
    COLLAB = re.compile(r"[@＠]|联动|合作|feat|联合|guest|嘉宾", re.I)
    todo = [bv for bv, v in videos.items()
            if bv not in details and (bv in hit or (v["mid"] in ok_authors and COLLAB.search(v["title"])) or v.get("union"))]
    log("详情阶段: 搜索共%d条, 基岩视频%d, 基岩UP%d, 已抓%d, 本轮待抓%d(跳过%d)"
        % (len(videos), len(hit), len(ok_authors), len(details), len(todo), len(videos) - len(details) - len(todo)))
    lock = threading.Lock()
    pause_until = [0.0]
    delay_floor = [0.7]  # 自适应油门: 风控时抬高, 平稳时缓慢回落
    tls = threading.local()
    counter = [0]

    def brake(code):
        with lock:
            pause_until[0] = max(pause_until[0], time.time() + 180)
            delay_floor[0] = min(8.0, delay_floor[0] * 2.0)
            log("风控刹车 code=%s: 全局暂停180s, delay_floor=%.1fs" % (code, delay_floor[0]))

    # 开工前先确认IP没被风控: 单条低频探测, 412就等冷却, 绝不顶着封锁开线程
    probe = Bili()
    while True:
        wait = 60
        try:
            d = probe.get("https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7h7")
            if d.get("code") in (0, -404, 62002, 62004):
                log("风控探测通过 code=%s, 开始详情抓取" % d.get("code"))
                break
            log("风控探测 code=%s, 60s后重试" % d.get("code"))
        except RiskError as e:
            log("IP仍在风控冷却(HTTP%d), 90s后重探" % e.status)
            wait = 90
        except Exception as e:
            log("探测异常 %r, 60s后重试" % e)
        time.sleep(wait)

    def thread_get(bili, path):
        import http.client
        if not hasattr(tls, "conn"):
            tls.conn = http.client.HTTPSConnection("api.bilibili.com", timeout=15)
        cookie = "; ".join("%s=%s" % (c.name, c.value) for c in bili.cj)
        try:
            tls.conn.request("GET", path, headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/",
                                                  "Accept": "application/json, text/plain, */*", "Cookie": cookie})
            r = tls.conn.getresponse()
            body = r.read()
            if r.status in (412, 403):
                raise RiskError(r.status)
            if r.status != 200:
                raise IOError("http %d" % r.status)
            return json.loads(body.decode("utf-8"))
        except Exception:
            try:
                tls.conn.close()
            except Exception:
                pass
            del tls.conn
            raise

    def worker(bv):
        while time.time() < pause_until[0]:
            time.sleep(2)
        if not hasattr(tls, "bili"):
            tls.bili = Bili()
        bili = tls.bili
        d = bili.call(lambda: thread_get(bili, "/x/web-interface/view?bvid=" + bv), "详情 " + bv, on_risk=brake)
        rec = None
        if d is None or d.get("code") != 0:
            code = (d or {}).get("code", "net")
            rec = {"err": code}
        else:
            dd = d["data"]
            ow = dd.get("owner") or {}
            rec = {"owner": {"mid": str(ow.get("mid")), "name": ow.get("name") or "", "face": ow.get("face") or ""},
                   "staff": [{"mid": str(s.get("mid")), "name": s.get("name") or "", "face": s.get("face") or ""}
                             for s in dd.get("staff", [])],
                   "title": dd.get("title") or "", "desc": dd.get("desc") or "",
                   "pubdate": dd.get("pubdate") or 0}
        with lock:
            details[bv] = rec
            if rec and "err" not in rec:
                for person in [rec["owner"]] + rec["staff"]:
                    if person["mid"] and person["mid"] != "0":
                        faces[person["mid"]] = {"name": person["name"], "face": person["face"]}
            counter[0] += 1
            if counter[0] % 200 == 0:
                save("details", details); save("faces", faces)
                log("详情进度 %d/%d (%.1f%%)" % (counter[0], len(todo), 100.0 * counter[0] / max(1, len(todo))))
                if delay_floor[0] > 0.7 and time.time() > pause_until[0]:
                    delay_floor[0] = max(0.7, delay_floor[0] * 0.9)
        time.sleep(random.uniform(delay_floor[0], delay_floor[0] + 0.3))

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(worker, todo))
    save("details", details); save("faces", faces)
    ok = sum(1 for v in details.values() if "err" not in v)
    log("详情阶段完成: 成功 %d / %d" % (ok, len(details)))

if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "search"
    if phase == "search":
        phase_search()
    elif phase == "space":
        phase_space()
    elif phase == "mcbe":
        phase_mcbe_months()
    elif phase == "big":
        phase_big()
    elif phase == "week":
        phase_week()
    elif phase == "union":
        phase_union()
    elif phase == "staffmc":
        phase_staffmc()
    elif phase == "details":
        phase_details()
    else:
        print("unknown phase")