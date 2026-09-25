#!/usr/bin/env python3
"""一次性侦察：候选池实时价/昨收/是否追高 + 持仓卖出纪律命中判定（不落账）"""
import sys
import sqlite3
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import numpy as np
import duckdb
from core.prices import fetch_prices_batch

state = sqlite3.connect(str(BASE / 'ledger.db'), timeout=30)
state.execute("PRAGMA journal_mode=WAL")
state.execute("ATTACH DATABASE ? AS sig", (str(BASE / 'signals.db'),))
tdu = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)

today = '2026-09-25'
td = '20260925'
d = state.execute(
    "SELECT MAX(REPLACE(date,'-','')) FROM sig.fusion_center_signals WHERE REPLACE(date,'-','') < ?",
    (td,)).fetchone()[0]
print('signal_date:', d)

ct = {r[0]: float(r[1]) for r in state.execute(
    "SELECT stock_code, score FROM sig.fusion_center_signals WHERE REPLACE(date,'-','')=? AND score IS NOT NULL",
    (d,)).fetchall()}
md = {r[0]: float(r[1]) for r in state.execute(
    "SELECT stock_code, fusion_score FROM sig.signal_history WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL",
    (d,)).fetchall()}
common = sorted(set(ct) & set(md))
n = len(common)
ct_rank = np.argsort(np.argsort([ct[c] for c in common])) + 1
md_rank = np.argsort(np.argsort([md[c] for c in common])) + 1
comb = {c: round(0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100, 2)
        for i, c in enumerate(common)}
picks = sorted(comb.items(), key=lambda x: -x[1])[:15]
pool15 = [c for c, _ in picks]

pos = state.execute(
    "SELECT code, name, shares, avg_cost, buy_date, peak_price FROM strategy_positions "
    "WHERE account_id='agent_auto'").fetchall()
all_codes = sorted({c for c, *_ in pos} | set(pool15))
rtp = fetch_prices_batch(all_codes)

prev_map = {}
last_d = tdu.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
for r in tdu.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (last_d,)).fetchall():
    prev_map[r[0].split('.')[0]] = float(r[1])
print('prev trade_date in db:', last_d)

# 交易日计数（买入日之后的交易日数）
def hold_days(buy_date):
    try:
        return int(tdu.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ? AND trade_date <= ?",
            (str(buy_date).replace('-', ''), td)).fetchone()[0])
    except Exception:
        return None

names = {}
try:
    for r in tdu.execute("SELECT ts_code, name FROM stock_basic").fetchall():
        names[r[0].split('.')[0]] = r[1]
except Exception:
    pass

print('\n=== 候选池前15 ===')
print('rank code   combo   live   prev   chg%   note')
for i, c in enumerate(pool15, 1):
    px = rtp.get(c)
    pv = prev_map.get(c)
    chg = round((px / pv - 1) * 100, 2) if px and pv else None
    note = ''
    if chg is not None and chg >= 7:
        note = '追高(拒)'
    print(f'{i:>4} {c} {comb[c]:>7} {px} {pv} {chg} {note}')

print('\n=== 持仓纪律判定 ===')
print('code   name       shares  cost   live   pnl%   peak   dd%    hd  inpool')
for c, nm, sh, cost, bd, pk in pos:
    px = rtp.get(c) or cost
    pnl = round((px / cost - 1) * 100, 2)
    dd = round((px / pk - 1) * 100, 2) if pk else None
    hd = hold_days(bd)
    inp = c in pool15
    flags = []
    if pnl <= -8:
        flags.append('止损')
    if pk and pk >= cost * 1.05 and px / pk - 1 <= -0.08:
        flags.append('止盈回撤')
    if hd is not None and hd >= 20 and pnl < 5:
        flags.append('时间止损')
    if (not inp) and pnl < 0:
        flags.append('信号退出')
    print(f'{c} {nm:<8} {sh:>7} {cost:>6} {px:>6} {pnl:>6} {pk} {dd} {hd} {inp} {" ".join(flags)}')

print('\n=== 其他 ===')
cash = state.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id='agent_auto'").fetchone() if False else None
print('pool size total:', n)
state.close()
tdu.close()
