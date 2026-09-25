#!/usr/bin/env python3
"""cron 临时核查：agent_auto 候选/持仓 实时价 + 合成分排名 + 3日累计 (只读)"""
import sys
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import numpy as np, duckdb, sqlite3
from core.prices import fetch_prices_batch

state = sqlite3.connect(str(BASE / 'ledger.db'), timeout=30)
state.execute("ATTACH DATABASE ? AS sig", (str(BASE / 'signals.db'),))
tdu = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
d = '20260915'
ct = {r[0]: float(r[1]) for r in state.execute(
    "SELECT stock_code, score FROM sig.fusion_center_signals WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (d,))}
md = {r[0]: float(r[1]) for r in state.execute(
    "SELECT stock_code, fusion_score FROM sig.signal_history WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (d,))}
common = sorted(set(ct) & set(md))
n = len(common)
ct_rank = np.argsort(np.argsort([ct[c] for c in common])) + 1
md_rank = np.argsort(np.argsort([md[c] for c in common])) + 1
comb = {c: 0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100 for i, c in enumerate(common)}
order = sorted(comb.items(), key=lambda x: -x[1])
rank = {c: i + 1 for i, (c, _) in enumerate(order)}
print(f'universe={n}')
hold = ['300274', '301053', '301338', '603811', '688021']
cand = [c for c, _ in order[:20]]
codes = sorted(set(hold + cand))
px = fetch_prices_batch(codes)
prev = {}
for r in tdu.execute("SELECT ts_code, close, trade_date FROM daily WHERE trade_date=(SELECT MAX(trade_date) FROM daily)").fetchall():
    prev[r[0].split('.')[0]] = float(r[1])
r3 = {}
for c in codes:
    rows = tdu.execute("SELECT close FROM (SELECT trade_date, close, ROW_NUMBER() OVER (ORDER BY trade_date DESC) rn FROM daily WHERE ts_code LIKE ?) WHERE rn<=4 ORDER BY trade_date", (c + '.%',)).fetchall()
    cl = [float(x[0]) for x in rows]
    r3[c] = round((cl[-1] / cl[0] - 1) * 100, 2) if len(cl) >= 4 else None
names = {r[0].split('.')[0]: r[1] for r in tdu.execute("SELECT ts_code, name FROM stock_basic").fetchall()}
print(f"{'code':>7} {'name':<8} {'rank':>6} {'combo':>6} {'ctr':>7} {'mdl':>5} {'live':>8} {'prev':>8} {'chg%':>6} {'3d%':>7} tag")
for c in codes:
    p = px.get(c); pv = prev.get(c)
    chg = round((p / pv - 1) * 100, 2) if p and pv else None
    tag = 'HOLD' if c in hold else ''
    print(f"{c:>7} {names.get(c,'?'):<8} {rank.get(c,0):>6} {comb.get(c,0):>6.2f} {ct.get(c,0):>7.3f} {md.get(c,0):>5.2f} {p if p else 0:>8.2f} {pv if pv else 0:>8.2f} {chg if chg is not None else 0:>6} {r3.get(c) if r3.get(c) is not None else 0:>7} {tag}")
state.close(); tdu.close()
