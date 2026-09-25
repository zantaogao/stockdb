#!/usr/bin/env python3
"""只读诊断：查 backfill_stk_factor.sh 相关 cron 任务的调度/近期执行记录（只读）。"""
import json, os, sqlite3, time

C = os.path.expanduser("~/.hermes/cron")
j = json.load(open(f"{C}/jobs.json"))
jobs = j if isinstance(j, list) else j.get("jobs", j)
if isinstance(jobs, dict):
    jobs = list(jobs.values())

print("=== 相关任务（script 含 backfill_stk_factor）===")
ids = []
for it in jobs:
    if not isinstance(it, dict):
        continue
    if "backfill_stk_factor" in str(it.get("script") or ""):
        ids.append(it.get("id"))
        print(f"id={it.get('id')} name={it.get('name')!r} schedule={it.get('schedule')!r} "
              f"enabled={it.get('enabled')} last={it.get('last_run')} next={it.get('next_run')} "
              f"script={it.get('script')}")

print("\n=== 22:00-22:40 窗口内其它 enabled 任务 ===")
for it in jobs:
    if not isinstance(it, dict) or not it.get("enabled"):
        continue
    s = str(it.get("schedule") or "")
    if s.startswith("22") or "22 " in s:
        print(f"  id={it.get('id')} name={it.get('name')!r} schedule={s} script={it.get('script')}")

print("\n=== executions.db ===")
p = f"{C}/executions.db"
print("size:", os.path.getsize(p) if os.path.exists(p) else "MISSING")
try:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("tables:", tabs)
    for t in tabs:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        print(f"  {t} cols={cols}")
    c.close()
except Exception as e:
    print("ERR", repr(e))

print("\n=== 今日执行记录（近 40 条，含 stdout 尾部标记）===")
try:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    for t in ("executions", "runs", "job_runs"):
        try:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        except Exception:
            continue
        if not cols:
            continue
        tcol = "started_at" if "started_at" in cols else ("created_at" if "created_at" in cols else cols[0])
        rows = c.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 40").fetchall()
        print(f"--- {t} ---")
        for r in rows:
            d = dict(zip(cols, r))
            print("  ", {k: (v[:120] if isinstance(v, str) else v) for k, v in d.items()})
        break
    c.close()
except Exception as e:
    print("ERR", repr(e))
