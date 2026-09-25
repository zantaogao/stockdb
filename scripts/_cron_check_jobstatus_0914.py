#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 jobs.json 中策略/账户相关任务的 last_status（判断本轮日更是否记绿）"""
import json, os

p = os.path.expanduser("~/.hermes/cron/jobs.json")
d = json.load(open(p, encoding="utf-8"))
jobs = d if isinstance(d, list) else (d.get("jobs") or [])
if isinstance(jobs, dict):
    jobs = list(jobs.values())
for j in jobs:
    nm = (j.get("name") or "") + (j.get("id") or "")
    if any(k in nm for k in ("策略", "账户", "日更", "agent_trade", "持仓")):
        print({k: j.get(k) for k in ("id", "name", "schedule", "enabled", "last_status", "last_run", "last_error", "last_duration")})
