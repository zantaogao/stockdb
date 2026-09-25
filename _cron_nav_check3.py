#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 sim_accounts JSON nav_history 极端值 + 面板 NAV 曲线数据源"""
import json, os, sqlite3
BASE = os.path.expanduser('~/.hermes/stockdb')

print("--- sim_accounts JSON nav_history 检查 ---")
for aid in ['fusion3f', 'cmmr', 'cmmr_fusion', 'fusion_center', 'fusion_dual']:
    f = os.path.join(BASE, 'sim_accounts', f'{aid}.json')
    if not os.path.exists(f):
        print(f"  {aid}: 无 JSON")
        continue
    acct = json.load(open(f))
    nh = acct.get('nav_history', [])
    bad = [h for h in nh if abs(h.get('returns', 0)) > 50]
    print(f"  {aid}: nav_history {len(nh)} 条, |returns|>50% 的 {len(bad)} 条")
    for h in bad[:5]:
        print(f"    {h.get('date')} nav={h.get('nav')} returns={h.get('returns')}%")
    # 最后3条
    if nh:
        print(f"    最新3条: {[(h.get('date'), h.get('nav'), h.get('returns')) for h in nh[-3:]]}")

print("\n--- 面板 NAV 曲线 API ---")
import subprocess
out = subprocess.run(['grep', '-n', 'nav_history\|nav-history\|/api/nav\|api/strategy-nav\|nav_hist'],
                     capture_output=True, text=True, cwd=BASE)
print(out.stdout or "无匹配")
