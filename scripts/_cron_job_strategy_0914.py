#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 策略账户日更 cron 任务定义 + 最近执行结果"""
import json, os, glob

p = os.path.expanduser("~/.hermes/cron/jobs.json")
d = json.load(open(p, encoding="utf-8"))
jobs = d.get("jobs", d) if isinstance(d, dict) else d
if isinstance(jobs, dict):
    jobs = list(jobs.values())
print("total jobs:", len(jobs))
for j in jobs:
    blob = json.dumps(j, ensure_ascii=False)
    if "策略账户" in blob or "strategy_accounts_daily" in blob:
        print("=" * 60)
        for k in ("id", "name", "schedule", "cron", "enabled", "last_run", "last_status", "last_error", "next_run", "mode", "script", "command"):
            if k in j:
                print(f"  {k}: {str(j[k])[:600]}")
        pr = j.get("prompt") or ""
        if pr:
            print("  prompt(head 600):", pr[:600].replace("\n", " | "))
