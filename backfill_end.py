# -*- coding: utf-8 -*-
"""为旧进程已完成的任务回填 END 标记, 使续跑整组跳过。仅在搜索进程退出后运行。"""
import json, os, re
from crawl import KEYWORDS, YEARS, load, save, STATE

done = set(load("search_done", []))
failed = set()
logp = os.path.join(STATE, "crawl.log")
if os.path.exists(logp):
    for line in open(logp, encoding="utf-8"):
        m = re.search(r"跳过 (.+)\|\d+$", line.strip())
        if m:
            failed.add(m.group(1))
tasks = []
for kw in KEYWORDS:
    for y in YEARS:
        tasks.append((kw, str(y), "totalrank"))
    tasks.append((kw, "all", "pubdate"))
    tasks.append((kw, "all", "click"))
added = 0
for kw, sl, order in tasks:
    base = "%s|%s|%s" % (kw, sl, order)
    if base in failed or base + "|END" in done:
        continue
    pages = [p for p in range(1, 51) if "%s|%d" % (base, p) in done]
    if not pages:
        continue
    mx = max(pages)
    if all(("%s|%d" % (base, p)) in done for p in range(1, mx + 1)):
        done.add(base + "|END")
        added += 1
save("search_done", sorted(done))
print("回填 END 标记 %d 组" % added)