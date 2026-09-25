#!/usr/bin/env python3
"""NAV 完整性: sim_accounts JSON nav_history 最新日期/今日行/dup"""
import json, glob, os
SIM = '/Users/zantao/.hermes/stockdb/sim_accounts'
for p in sorted(glob.glob(os.path.join(SIM, '*.json'))):
    b = os.path.basename(p)
    if b.startswith('.'):
        continue
    try:
        d = json.load(open(p))
    except Exception as e:
        print(f"{b}: LOAD FAIL {e}"); continue
    if not isinstance(d, dict) or 'cash' not in d:
        print(f"{b}: 跳过"); continue
    h = [x for x in (d.get('nav_history') or []) if isinstance(x, dict)]
    raw = [str(x.get('date','')).replace('-','') for x in h]
    today = [x for x in h if str(x.get('date','')).replace('-','') == '20260915']
    print(f"{b:20s} closed={d.get('closed', False)!s:5s} n={len(raw):3d} latest={max(raw) if raw else None} "
          f"dup={len(raw)-len(set(raw))} today_rows={len(today)} "
          f"today_nav={[x.get('nav') for x in today]} cash={float(d.get('cash',0)):,.0f} pos={len(d.get('positions',[]))}")
