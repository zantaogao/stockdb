#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, glob
d = os.path.expanduser("~/.hermes/cron/output/051af215dc32")
files = sorted(glob.glob(os.path.join(d, "*.md")))
print(f"留存 output 份数: {len(files)}  最早: {os.path.basename(files[0])}  最新: {os.path.basename(files[-1])}")
hit = [os.path.basename(f) for f in files if "停牌" in open(f, encoding="utf-8", errors="ignore").read()]
print("含『停牌』字样的历史份数:", len(hit), hit[:10])

print("\n=== 今日各 tick 的账户 NAV 序列（从 output md 的对比块提取）===")
pat = re.compile(r"^(\S+?) \((cmmr|cmmr_fusion|fusion_center|center_dual|agent_auto)\).*?NAV=([\d,]+)\s+累计([-+]?[\d.]+)%", re.M)
for f in files:
    b = os.path.basename(f)
    if "2026-09-14" not in b:
        continue
    txt = open(f, encoding="utf-8", errors="ignore").read()
    vals = {m.group(2): (m.group(3), m.group(4)) for m in pat.finditer(txt)}
    if vals:
        fc = vals.get("fusion_center", ("?", "?"))
        print(f"  {b[11:19]}  fusion_center NAV={fc[0]:>9s} ({fc[1]}%) | cmmr={vals.get('cmmr',('?',))[0]} | center_dual={vals.get('center_dual',('?',))[0]} | agent_auto={vals.get('agent_auto',('?',))[0]}")
