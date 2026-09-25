#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列 15:00 以后会写 strategy_accounts 的 cron 任务（只读 jobs.json）"""
import json, os
d = json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json"), encoding="utf-8"))
jobs = d.get("jobs", d) if isinstance(d, dict) else d
if isinstance(jobs, dict):
    jobs = list(jobs.values())
for j in jobs:
    blob = json.dumps(j, ensure_ascii=False)
    if "strategy_accounts_daily" in blob or "strategy_accounts" in blob:
        sch = (j.get("schedule") or {}).get("expr")
        print(f"[{j.get('id')}] {j.get('name')} | {sch} | enabled={j.get('enabled')} | {j.get('script')}")
print("\n--- 今日(周一) 15:00 之后的所有任务 ---")
for j in jobs:
    sch = (j.get("schedule") or {}).get("expr", "")
    if not j.get("enabled"):
        continue
    m = sch.split()
    if len(m) == 5 and m[1].isdigit() and int(m[1]) >= 15:
        print(f"  {sch:22s} {j.get('name')} | script={j.get('script')}")
