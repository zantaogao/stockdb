#!/usr/bin/env python3
"""午盘裁决辅助：持仓/流水核对 + 候选池实时价/昨收/3日累计 + 可买股数测算"""
import json, sqlite3, sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import duckdb
from core.prices import fetch_prices_batch

state = sqlite3.connect(str(BASE / 'ledger.db'))
tdu = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
today = datetime.now().strftime('%Y-%m-%d')

print('=== holdings 全量 ===')
cols = [d[0] for d in state.execute("PRAGMA table_info(holdings)")]
print(cols)
for r in state.execute("SELECT * FROM holdings"):
    print(r)

print('\n=== 近3日 trade_log (agent_auto) ===')
for r in state.execute("SELECT trade_date, trade_time, code, name, direction, price, quantity, amount, notes "
                       "FROM trade_log WHERE strategy='agent_auto' ORDER BY id DESC LIMIT 12"):
    print(r)

cands = ["603811","301338","300274","688021","300176","002864","300971","688410","300724",
         "301601","603040","300658","603211","688148","688125"]
px = fetch_prices_batch(cands)
last_date = tdu.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print(f'\n=== 候选池 实时/昨收({last_date})/3日累计 ===')
rows = []
for c in cands:
    closes = [float(x[0]) for x in tdu.execute(
        "SELECT close FROM (SELECT trade_date, close, ROW_NUMBER() OVER (ORDER BY trade_date DESC) rn "
        "FROM daily WHERE ts_code LIKE ?) WHERE rn<=4 ORDER BY trade_date", (c + '.%',)).fetchall()]
    prev = closes[-1] if closes else None
    p = px.get(c)
    chg = round((p / prev - 1) * 100, 2) if p and prev else None
    cum3 = round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) >= 4 else None
    rows.append((c, p, prev, chg, cum3))
    print(f'{c} live={p} prev={prev} chg={chg}% 3d={cum3}%')

print('\n=== 可买股数(额度19965) ===')
for c, p, prev, chg, cum3 in rows:
    if p:
        sh = int(19965 // p // 100 * 100)
        print(f'{c} @{p} 可买{sh}股 ≈{sh*p:,.0f}元  当日{chg}% 3d{cum3}%')
state.close(); tdu.close()
