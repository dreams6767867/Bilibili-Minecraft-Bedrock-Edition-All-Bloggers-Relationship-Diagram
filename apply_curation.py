# -*- coding: utf-8 -*-
"""在 v11 数据上应用人工策展: 删除名单 + 对新增创作者扫描其联合投稿(标签含我的世界)并全员连线"""
import json, os, re, time, random, calendar
import crawl

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state")
ERA_SPLIT = calendar.timegm((2017, 9, 20, 0, 0, 0)) - 8 * 3600
ADD_MIDS = {"634497653": "Vyxw", "3493129076345390": "墨鱼大杂烩CuttleFish"}
MC_TAG = re.compile(r"我的世界")

def era_of(ts):
    return "pe" if ts and ts < ERA_SPLIT else "br"

def main():
    txt = open(os.path.join(BASE, "data.js"), encoding="utf-8").read()
    G = json.loads(txt.split("=", 1)[1].rstrip().rstrip(";"))
    nodes = {n["id"]: n for n in G["nodes"]}
    links = G["links"]
    cur = json.load(open(r"C:\Users\ZHAO1\Downloads\curation (1).json", encoding="utf-8"))
    del_ids = {str(x["id"]) for x in cur.get("delete", []) if x.get("id")}
    b = crawl.Bili()
    union_bvids = []
    for mid, name in ADD_MIDS.items():
        pn = 1
        nump = 1
        while pn <= min(3, nump):
            d = b.call(lambda: b.signed_get("search/type", {
                "search_type": "video", "keyword": name, "page": pn,
                "page_size": 30, "order": "pubdate"}), "addscan %s p%d" % (name, pn), tries=3)
            if not d or d.get("code") != 0:
                break
            data = d.get("data") or {}
            rs = data.get("result") or []
            nump = data.get("numPages") or 1
            for v in rs:
                if str(v.get("mid")) != mid or not v.get("is_union_video"):
                    continue
                tag = v.get("tag") or ""
                if not MC_TAG.search(tag):
                    continue
                union_bvids.append(v.get("bvid"))
            if not rs or pn >= nump:
                break
            pn += 1
            time.sleep(random.uniform(0.8, 1.2))
    print("新增创作者联投(标签含我的世界):", len(union_bvids), union_bvids)

    edge_map = {}
    def add_edge(a, z, era, joint=True):
        if not a or not z or a == z:
            return
        if a not in nodes or z not in nodes:
            return
        k = (a, z) if a < z else (z, a)
        e = edge_map.setdefault(k, {"pe": 0, "br": 0, "j": 0})
        if era:
            e[era] = 1
        if joint:
            e["j"] = 1

    for bv in union_bvids:
        d = b.call(lambda: b.get("https://api.bilibili.com/x/web-interface/view?bvid=" + bv), "view " + bv, tries=3)
        if not d or d.get("code") != 0:
            continue
        dd = d["data"]
        ow = dd.get("owner") or {}
        party = [{"mid": str(ow.get("mid")), "name": ow.get("name") or "", "face": ow.get("face") or ""}]
        for s in dd.get("staff", []):
            if s.get("mid") and str(s.get("mid")) != "0":
                party.append({"mid": str(s["mid"]), "name": s.get("name") or "", "face": s.get("face") or ""})
        era = era_of(dd.get("pubdate") or 0)
        for p in party:
            if p["mid"] not in nodes:
                nodes[p["mid"]] = {"id": p["mid"], "name": p["name"], "face": p["face"],
                                   "pe": 0, "br": 0, "vpe": 0, "vbr": 0}
            nodes[p["mid"]][era] = 1
        for i in range(len(party)):
            for j in range(i + 1, len(party)):
                add_edge(party[i]["mid"], party[j]["mid"], era)
        time.sleep(random.uniform(0.8, 1.2))

    links = [l for l in links if l["source"] not in del_ids and l["target"] not in del_ids]
    nodes_out = [n for n in nodes.values() if n["id"] not in del_ids]
    have = {(l["source"], l["target"]) for l in links}
    for k, e in edge_map.items():
        links.append({"source": k[0], "target": k[1], "pe": e["pe"], "br": e["br"], "j": e["j"]})
    nodes_out.sort(key=lambda x: -(x["vpe"] + x["vbr"]))
    graph = {"nodes": nodes_out, "links": links, "eraSplit": "2017-09-20"}
    json.dump(graph, open(os.path.join(BASE, "graph.json"), "w", encoding="utf-8"), ensure_ascii=False)
    with open(os.path.join(BASE, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.GRAPH="); json.dump(graph, f, ensure_ascii=False); f.write(";")
    os.makedirs(STATE, exist_ok=True)
    json.dump({"delete": [{"id": i} for i in sorted(del_ids)],
               "add": [{"id": m, "name": n} for m, n in ADD_MIDS.items()]},
              open(os.path.join(STATE, "curation.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("完成: nodes", len(nodes_out), "links", len(links))

if __name__ == "__main__":
    main()