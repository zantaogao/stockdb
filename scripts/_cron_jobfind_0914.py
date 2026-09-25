#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读：找策略账户日更 cron 任务定义"""
import json, os, glob
p = os.path.expanduser("~/.hermes/cron/jobs.json")
d = json.load(open(p, encoding="utf-8"))
jobs = d if isinstance(d, list) else d.get("jobs", d)
if isinstance(jobs, dict):
    jobs = list(jobs.values())
print("total jobs:", len(jobs))
for j in jobs:
    s = json.dumps(j, ensure_ascii=False)
    if "策略账户" in s or "strategy_accounts" in s:
        print(json.dumps({k: v for k, v in j.items() if k in
              ("id", "name", "schedule", "cron", "command", "prompt", "enabled",
               "last_run", "last_status", "next_run", "no_agent", "model")}, ensure_ascii=False, indent=1)[:2000])
        print("---")
