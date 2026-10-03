#!/usr/bin/env python3
"""盘后深复盘只读取数 2026-09-29"""
import duckdb, sqlite3, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{BASE}/tushare.db', read_only=True)

# ---------- 板块近10交易日走势（daily JOIN stock_basic.industry，与 daily_report 同口径） ----------
days = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 10").fetchall()]
days = sorted(days)
print("DATES:", days)
ind_daily = {}  # date -> {ind: avg}
for d in days:
    rows = t.execute("""
        SELECT b.industry, AVG(d.pct_chg), COUNT(*) FROM daily d
        JOIN stock_basic b ON b.ts_code=d.ts_code
        WHERE d.trade_date=? AND b.industry IS NOT NULL AND b.industry!=''
        GROUP BY 1 HAVING COUNT(*)>=10""", [d]).fetchall()
    ind_daily[d] = {r[0]: r[1] for r in rows}
last5 = days[-5:]
cum5 = {}
for d in last5:
    for ind, v in ind_daily[d].items():
        cum5[ind] = cum5.get(ind, 0) + v
def streak(ind):
    s = 0
    for d in reversed(last5):
        v = ind_daily[d].get(ind)
        if v is None or v <= 0: break
        s += 1
    return s
print("== TOP 5D CUM ==")
for ind, c in sorted(cum5.items(), key=lambda x: -x[1])[:12]:
    print(f"  {ind} cum5={c:+.2f} streak={streak(ind)} last5=" + " ".join(f"{ind_daily[d].get(ind, float('nan')):+.2f}" for d in last5))
print("== BOT 5D CUM ==")
for ind, c in sorted(cum5.items(), key=lambda x: x[1])[:8]:
    print(f"  {ind} cum5={c:+.2f} last5=" + " ".join(f"{ind_daily[d].get(ind, float('nan')):+.2f}" for d in last5))
print("== DAILY RANKS of key boards ==")
key = ['全国地产','半导体','区域地产','软件服务','元器件','专用机械','染料涂料','生物制药','农药化肥','多元金融','交通设备','化学制药']
for d in last5:
    dd = ind_daily[d]
    rank = sorted(dd.items(), key=lambda x: -x[1])
    pos = {ind: (r+1, v) for r, (ind, v) in enumerate(rank)}
    print(d, " n_ind=", len(rank), {b: f"r{pos[b][0]}({pos[b][1]:+.2f})" for b in key if b in pos})
# 10日全序列 for key boards
print("== KEY BOARD 10d daily avg ==")
for b in key:
    print(b, [round(ind_daily[d].get(b, 0.0), 2) for d in days])

# ---------- 主账户持仓 ----------
print("\n== HOLDINGS ==")
led = sqlite3.connect(f'{BASE}/ledger.db'); led.row_factory = sqlite3.Row
for r in led.execute("SELECT * FROM holdings").fetchall():
    print(dict(r))
print("\n== WATCHLIST ==")
try:
    for r in led.execute("SELECT * FROM watchlist ORDER BY rowid DESC LIMIT 15").fetchall():
        print(dict(r))
except Exception as e: print("err", e)
print("\n== trade_cooldown ==")
try:
    for r in led.execute("SELECT * FROM trade_cooldown ORDER BY rowid DESC LIMIT 10").fetchall():
        print(dict(r))
except Exception as e: print("err", e)
print("\n== trade_tp_ban ==")
try:
    for r in led.execute("SELECT * FROM trade_tp_ban ORDER BY rowid DESC LIMIT 10").fetchall():
        print(dict(r))
except Exception as e: print("err", e)

# ---------- IC 序列 ----------
sig = sqlite3.connect(f'{BASE}/signals.db'); sig.row_factory = sqlite3.Row
print("\n== ic_daily last 12 ==")
print("cols:", [r[1] for r in sig.execute("PRAGMA table_info(ic_daily)").fetchall()])
for r in sig.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 12").fetchall():
    print(dict(r))
for tbl, dcol in [('fusion_ic_daily','date'), ('center_dual_ic_daily','signal_date'), ('cmmr_ic_daily','date')]:
    print(f"\n== {tbl} last 12 ==")
    cols = [r[1] for r in sig.execute(f"PRAGMA table_info({tbl})").fetchall()]
    print("cols:", cols)
    dc = dcol if dcol in cols else cols[0]
    try:
        for r in sig.execute(f"SELECT * FROM {tbl} ORDER BY {dc} DESC LIMIT 12").fetchall():
            print(dict(r))
    except Exception as e: print("err", e)
print("\n== ic_window last 15 ==")
print("cols:", [r[1] for r in sig.execute("PRAGMA table_info(ic_window)").fetchall()])
for r in sig.execute("SELECT * FROM ic_window ORDER BY rowid DESC LIMIT 15").fetchall():
    print(dict(r))
