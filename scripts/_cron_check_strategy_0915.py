#!/usr/bin/env python3
# 监督任务核对：strategy_accounts_daily 本轮(20260915)是否正常
# 只读，不写任何库
import sqlite3, json, os, glob, datetime

HOME = os.path.expanduser('~')
LEDGER = os.path.join(HOME, '.hermes/stockdb/ledger.db')
SIM = os.path.join(HOME, '.hermes/stockdb/sim_accounts')
TODAY = '20260915'

print('=== 1. ledger.db NAV 最新日期 (表探测) ===')
con = sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True)
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('tables:', tabs)
cand = [t for t in tabs if 'nav' in t.lower()]
print('nav-like tables:', cand)
for t in cand:
    cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
    print(f'-- {t} cols={cols}')
    dc = 'date' if 'date' in cols else cols[0]
    ac = 'account_id' if 'account_id' in cols else ('account' if 'account' in cols else None)
    if ac:
        rows = con.execute(
            f"SELECT {ac}, MAX(REPLACE({dc},'-','')) mx, COUNT(*) FROM {t} GROUP BY {ac} ORDER BY {ac}"
        ).fetchall()
    else:
        rows = con.execute(f"SELECT NULL, MAX(REPLACE({dc},'-','')), COUNT(*) FROM {t}").fetchall()
    for r in rows:
        print(f'   {r[0]}: latest={r[1]} rows={r[2]}')

print()
print('=== 2. sim_accounts JSON (closed 标记/最新日期/现金) ===')
for p in sorted(glob.glob(os.path.join(SIM, '*.json'))):
    b = os.path.basename(p)
    if b.startswith('.'):
        continue
    try:
        d = json.load(open(p))
    except Exception as e:
        print(f'{b}: LOAD FAIL {e}')
        continue
    if not isinstance(d, dict) or 'cash' not in d or not isinstance(d.get('positions'), list):
        print(f'{b}: 跳过(结构不符)')
        continue
    hist = d.get('nav_history') or []
    raw = [str(h.get('date', '')).replace('-', '') for h in hist if isinstance(h, dict)]
    dup = len(raw) - len(set(raw))
    latest = max(raw) if raw else None
    print(f'{b}: closed={d.get("closed", False)} latest_nav={latest} n={len(raw)} dup_same_day={dup} '
          f'cash={float(d.get("cash", 0)):,.0f} pos={len(d["positions"])} '
          f'last_rebalance={d.get("last_rebalance_date")}')

print()
print('=== 3. 今日成交(trade_log / ledger 流水表) ===')
for t in tabs:
    if 'trade' in t.lower() or 'ledger' in t.lower() or 'record' in t.lower() or 'txn' in t.lower():
        cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
        dc = next((c for c in cols if c.lower() in ('date', 'trade_date', 'ts', 'time')), None)
        if not dc:
            continue
        n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE REPLACE({dc},'-','') LIKE ?", (TODAY + '%',)).fetchone()[0]
        print(f'{t}({dc}): today_rows={n}')
con.close()
print('done', datetime.datetime.now().isoformat())
