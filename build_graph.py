# -*- coding: utf-8 -*-
"""从抓取状态构建合作图: 严格基岩过滤 -> 时代划分(2017-09-20) -> 节点/边 -> graph.json/data.js
节点: {id,name,face,pe,br,vpe,vbr}  pe/br=该时代是否活跃, vpe/vbr=该时代投稿数
边:   {source,target,pe,br,j}      j=含联合投稿
"""
import json, os, re, collections, time, calendar

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state")
ERA_SPLIT = calendar.timegm((2017, 9, 20, 0, 0, 0)) - 8 * 3600

def load(name, default):
    p = os.path.join(STATE, name + ".json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default

STRONG = re.compile(r"基岩|bedrock|mcbe|mcpe|携带版|addon|行为包|pocket\s*edition|minecraft\s*pe|(?<![A-Za-z])pe(?![A-Za-z])", re.I)
WEAK = re.compile(r"手机版|移动版|手游|安卓|android|ios", re.I)
MCCTX = re.compile(r"我的世界|minecraft|(?<![A-Za-z])mc(?![A-Za-z])|网易|方块|苦力怕|史蒂夫|红石|生存|建造", re.I)

def bedrock_hit(title, desc, tag):
    text = "%s %s %s" % (title or "", desc or "", tag or "")
    if STRONG.search(text):
        return True
    return bool(WEAK.search(text) and MCCTX.search(text))

AT_RE = re.compile(r"[@＠]([一-鿿A-Za-z0-9_\-]{1,24})")

def match_at(text, names):
    found = set()
    for m in AT_RE.finditer(text or ""):
        s = m.group(1)
        for L in range(len(s), 0, -1):
            if s[:L] in names:
                found.add(s[:L])
                break
    return found

def era_of(pubdate):
    if not pubdate:
        return None
    return "pe" if pubdate < ERA_SPLIT else "br"

def main():
    videos = load("search_videos", {})
    details = load("details", {})
    faces = load("faces", {})

    # 1) 基岩视频判定 + 时代
    hit = {}   # bv -> era
    for bv, v in videos.items():
        d = details.get(bv) or {}
        title = d.get("title") or v["title"]
        desc = d.get("desc") or v["desc"]
        if bedrock_hit(title, desc, v.get("tag", "")):
            hit[bv] = era_of(d.get("pubdate") or v.get("pubdate") or 0)
    print("基岩视频: %d / %d (携带版 %d, 基岩版 %d, 未知 %d)"
          % (len(hit), len(videos), sum(1 for e in hit.values() if e == "pe"),
             sum(1 for e in hit.values() if e == "br"), sum(1 for e in hit.values() if e is None)))

    # 2) 节点
    nodes = {}
    def add_node(mid, name, face=""):
        if not mid or mid == "0":
            return
        n = nodes.setdefault(mid, {"name": name or "", "face": face or "",
                                   "pe": 0, "br": 0, "vpe": 0, "vbr": 0})
        if name:
            n["name"] = name
        if face:
            n["face"] = face
    def activate(mid, era):
        if era and mid in nodes:
            nodes[mid][era] = 1
    for bv, era in hit.items():
        v = videos[bv]
        add_node(v["mid"], v["author"])
        activate(v["mid"], era)
        if era:
            nodes[v["mid"]]["v" + era] += 1
    for bv, d in details.items():
        if "err" in d or bv not in hit:
            continue
        era = hit[bv]
        for s in d.get("staff", []):
            add_node(s["mid"], s["name"], s.get("face", ""))
            activate(s["mid"], era)
    for mid, n in nodes.items():
        f = faces.get(mid)
        if f:
            if f.get("face"):
                n["face"] = f["face"]
            if f.get("name") and not n["name"]:
                n["name"] = f["name"]

    names = {}
    for mid, n in sorted(nodes.items(), key=lambda kv: -(kv[1]["vpe"] + kv[1]["vbr"])):
        if n["name"] and n["name"] not in names:
            names[n["name"]] = mid

    # 3) 边 (按视频时代打标)
    edges = {}
    def add_edge(a, b, era, kind):
        if not a or not b or a == b or a not in nodes or b not in nodes:
            return
        k = (a, b) if a < b else (b, a)
        e = edges.setdefault(k, {"pe": 0, "br": 0, "j": 0})
        if era:
            e[era] = 1
        if kind == "joint":
            e["j"] = 1
        activate(a, era); activate(b, era)
    joint_videos = at_videos = 0
    for bv, d in details.items():
        if "err" in d or bv not in hit:
            continue
        era = hit[bv]
        ow = d["owner"]["mid"]
        staff = [s["mid"] for s in d.get("staff", []) if s["mid"] and s["mid"] != "0"]
        if staff:
            joint_videos += 1
            party = [ow] + staff
            for i in range(len(party)):
                for j in range(i + 1, len(party)):
                    add_edge(party[i], party[j], era, "joint")
        ats = match_at((d.get("title") or "") + "\n" + (d.get("desc") or ""), names)
        if ats:
            at_videos += 1
            for nm in ats:
                add_edge(ow, names[nm], era, "at")
    for bv, era in hit.items():
        if bv in details and "err" not in details[bv]:
            continue
        v = videos[bv]
        for nm in match_at(v["title"] + "\n" + v["desc"], names):
            add_edge(v["mid"], names[nm], era, "at")

    # 4) 输出
    node_list = [{"id": mid, "name": n["name"] or mid, "face": n["face"],
                  "pe": n["pe"], "br": n["br"], "vpe": n["vpe"], "vbr": n["vbr"]}
                 for mid, n in nodes.items()]
    node_list.sort(key=lambda x: -(x["vpe"] + x["vbr"]))
    links = [{"source": a, "target": b, "pe": e["pe"], "br": e["br"], "j": e["j"]}
             for (a, b), e in edges.items()]
    graph = {"nodes": node_list, "links": links, "eraSplit": "2017-09-20"}
    with open(os.path.join(BASE, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False)
    with open(os.path.join(BASE, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.GRAPH=")
        json.dump(graph, f, ensure_ascii=False)
        f.write(";")

    def view_stats(era):
        ns = [n for n in node_list if era is None or n[era]]
        ls = [l for l in links if era is None or l[era]]
        deg = collections.Counter()
        for l in ls:
            deg[l["source"]] += 1; deg[l["target"]] += 1
        return {"nodes": len(ns), "edges": len(ls),
                "isolated": sum(1 for n in ns if deg[n["id"]] == 0),
                "top10": [{"name": next(n["name"] for n in ns if n["id"] == m), "deg": d}
                          for m, d in deg.most_common(10)]}
    years = collections.Counter(time.strftime("%Y", time.localtime(videos[bv]["pubdate"]))
                                for bv in hit if videos[bv]["pubdate"])
    stats = {"videos_scanned": len(videos), "bedrock_videos": len(hit),
             "joint_videos": joint_videos, "at_videos": at_videos,
             "joint_edges": sum(1 for e in edges.values() if e["j"]),
             "year_dist": dict(sorted(years.items())),
             "all": view_stats(None), "pe": view_stats("pe"), "br": view_stats("br")}
    with open(os.path.join(STATE, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()