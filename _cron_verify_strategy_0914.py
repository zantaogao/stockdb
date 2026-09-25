#!/usr/bin/env python3
"""对账：策略账户 20260914 日更结果核对（只读）"""
import json, sqlite3, pathlib, datetime

SB = pathlib.Path.home() / '.hermes/stockdb'
TODAY = '20260914'
ACCTS = ['cmmr', 'cmmr_fusion', 'fusion_center', 'center_dual', 'agent_auto', 'fusion3f', 'fusion_dual']

print('=== JSON 账户 NAV 尾部 ===')
for a in ACCTS:
    p = SB / 'sim_accounts' / f'{a}.json'
    d = json.loads(p.read_text())
    hist = d.get('nav_history') or []
    hist = [h for h in hist if str(h.get('date', '')).replace('-', '') <= TODAY]
    last = hist[-1] if hist else {}
    pos = d.get('positions') or []
    print(f'{a:12s} mtime={datetime.datetime.fromtimestamp(p.stat().st_mtime):%m-%d %H:%M} '
          f'last_nav_date={str(last.get("date","")).replace("-","")} nav={last.get("nav")} '
          f'cash={round(d.get("cash", 0),2)} n_pos={len(pos)} trades={len(d.get("trade_log") or d.get("trades") or [])}')

print()
print('=== ledger.db strategy_positions (非零) ===')
c = sqlite3.connect(SB / 'ledger.db')
for r in c.execute("SELECT account_id, code, name, shares, avg_cost, buy_date, updated_at FROM strategy_positions ORDER BY account_id, code"):
    print(r)

print()
print('=== ledger.db trade_log 今日 (trade_date=20260914) ===')
cols = [r[1] for r in c.execute('PRAGMA table_info(trade_log)')]
print('cols:', cols)
for r in c.execute("SELECT * FROM trade_log WHERE REPLACE(COALESCE(trade_date,''),'-','')=? ", (TODAY,)):
    print(r)

print()
print('=== 各账户 NAV 序列尾部(JSON) ===')
for a in ACCTS:
    d = json.loads((SB / 'sim_accounts' / f'{a}.json').read_text())
    h = sorted(d.get('nav_history') or [], key=lambda x: str(x.get('date')))
    tail = [(str(x.get('date')).replace('-', ''), x.get('nav')) for x in h[-3:]]
    print(a, tail)
