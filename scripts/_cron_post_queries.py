#!/usr/bin/env python3
"""盘后报告只读补充查询（2026-09-29 postmarket cron）"""
import duckdb, sqlite3, json, os
BASE = os.path.expanduser('~/.hermes/stockdb')

# ---------- 1. 指数近5日 ----------
tush = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
print("== INDEX 5d ==")
for ts, name in [('000852.SH','中证1000'), ('000001.SH','上证'), ('000016.SH','上证50')]:
    rows = tush.execute("""
        SELECT trade_date, close, pct_chg, amount FROM index_daily_raw
        WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6""", [ts]).fetchall()
    print(name, list(reversed(rows)))

# ---------- 2. 行业板块近10日 ----------
print("\n== SW DAILY last 10 trade dates ==")
rows = tush.execute("""
    SELECT d.trade_date, b.industry_name, SUM(d.pct_chg)/COUNT(*) avg_pct, COUNT(*) n
    FROM sw_daily_raw d JOIN stock_industry_raw b ON d.ts_code=b.ts_code
    WHERE d.trade_date >= '20260916'
    GROUP BY 1,2 ORDER BY 1, avg_pct DESC""").fetchall()
# pivot: latest 5 days rank + 5d cum + streak
from collections import defaultdict
byday = defaultdict(list)
for td, ind, ap, n in rows:
    byday[td].append((ind, ap))
days = sorted(byday)[-5:]
print("days:", days)
cum = defaultdict(float)
for d in days:
    for ind, ap in byday[d]:
        cum[ind] += ap
# top10 by 5d cum
top = sorted(cum.items(), key=lambda x: -x[1])[:12]
# 连续强势天数（近5日中日涨幅>0的连续尾部天数）
def streak(ind):
    s = 0
    for d in reversed(days):
        day = dict(byday[d])
        v = day.get(ind)
        if v is None: break
        if v > 0: s += 1
        else: break
    return s
print("TOP5D_CUM (industry, cum5d, streak):")
for ind, c in top:
    print(f"  {ind} {c:.2f} streak={streak(ind)}")
bot = sorted(cum.items(), key=lambda x: x[1])[:6]
print("BOT5D_CUM:")
for ind, c in bot:
    print(f"  {ind} {c:.2f} streak={streak(ind)}")
# daily ranking of top boards last 5 days
boards = [i for i,_ in top[:6]]
for d in days:
    dd = dict(byday[d])
    rank = sorted(dd.items(), key=lambda x:-x[1])
    pos = {ind: (r+1, dd[ind]) for r,(ind,_) in enumerate(rank)}
    print(d, {b: f"rank{pos[b][0]} {pos[b][1]:+.2f}" for b in boards if b in pos})

# ---------- 3. ledger 持仓/止损距离 ----------
print("\n== LEDGER holdings ==")
led = sqlite3.connect(f'{BASE}/ledger.db')
led.row_factory = sqlite3.Row
cols = [r[1] for r in led.execute("PRAGMA table_info(holdings)")]
print("holdings cols:", cols)
for r in led.execute("SELECT * FROM holdings").fetchall():
    print(dict(r))
print("\n== watchlist ==")
try:
    for r in led.execute("SELECT * FROM watchlist").fetchall():
        print(dict(r))
except Exception as e:
    print("watchlist err", e)

# ---------- 4. strategy meta ----------
print("\n== strategy_accounts_meta ==")
try:
    for r in led.execute("SELECT account_id, config_json FROM strategy_accounts_meta").fetchall():
        print(r[0], r[1][:200])
except Exception as e:
    print("meta err", e)

# ---------- 5. IC 序列 ----------
print("\n== ic_daily last 10 ==")
sig = sqlite3.connect(f'{BASE}/signals.db')
sig.row_factory = sqlite3.Row
try:
    cols = [r[1] for r in sig.execute("PRAGMA table_info(ic_daily)")]
    print("ic_daily cols:", cols)
    for r in sig.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall():
        print(dict(r))
except Exception as e:
    print("ic_daily err", e)

for tbl in ['fusion_ic_daily','center_dual_ic_daily','cmmr_ic_daily']:
    print(f"\n== {tbl} last 10 ==")
    try:
        cols = [r[1] for r in sig.execute(f"PRAGMA table_info({tbl})")]
        print("cols:", cols)
        dcol = 'signal_date' if 'signal_date' in cols else ('date' if 'date' in cols else cols[0])
        for r in sig.execute(f"SELECT * FROM {tbl} ORDER BY {dcol} DESC LIMIT 10").fetchall():
            print(dict(r))
    except Exception as e:
        print(tbl, "err", e)

print("\n== ic_window ==")
try:
    cols = [r[1] for r in sig.execute("PRAGMA table_info(ic_window)")]
    print("cols:", cols)
    for r in sig.execute("SELECT * FROM ic_window ORDER BY rowid DESC LIMIT 12").fetchall():
        print(dict(r))
except Exception as e:
    print("ic_window err", e)
