#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, glob

for p in sorted(glob.glob(os.path.expanduser("~/.hermes/cron/jobs.json"))) + sorted(glob.glob(os.path.expanduser("~/.hermes/cron/*.json"))):
    print("FILE:", p, os.path.getsize(p))
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("  ERR", e); continue
    jobs = d if isinstance(d, list) else (d.get("jobs") or list(d.values()))
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    for j in jobs:
        if not isinstance(j, dict):
            continue
        s = json.dumps(j, ensure_ascii=False)
        if ("NAS" in s or "nas" in s) and ("backup" in s.lower() or "备份" in s):
            print("  ", {k: j.get(k) for k in ("id", "name", "schedule", "enabled", "last_status", "last_run", "last_error", "error", "next_run")})
print("\n=== nas_backup.log tail ===")
lg = os.path.expanduser("~/.hermes/logs/nas_backup.log")
lines = open(lg, encoding="utf-8", errors="replace").read().splitlines()
print("lines:", len(lines))
for l in lines[-40:]:
    print(l)
