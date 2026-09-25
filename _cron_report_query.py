import duckdb, sqlite3, json, datetime

# 1) index 5-day trend
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print("== index_daily_raw 近5日 ==")
try:
    rows = con.execute("""SELECT ts_code, trade_date, close, pct_chg FROM index_daily_raw
        WHERE ts_code IN ('000852.SH','000001.SH') AND trade_date >= '20260901'
        ORDER BY ts_code, trade_date""").fetchall()
    for r in rows: print(r)
except Exception as e:
    print("index_daily_raw err:", e)

print("== 近5个交易日列表 ==")
dts = con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260825' ORDER BY trade_date").fetchall()
print([d[0] for d in dts])

# 2) 主账户持仓距止损/止盈 (ledger holdings)
led = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
led.row_factory = sqlite3.Row
print("\n== holdings 表结构 ==")
cols = [c[1] for c in led.execute("PRAGMA table_info(holdings)")]
print(cols)
print("\n== holdings ==")
for r in led.execute("SELECT * FROM holdings").fetchall():
    print(dict(r))
print("\n== watchlist ==")
try:
    for r in led.execute("SELECT * FROM watchlist").fetchall():
        print(dict(r))
except Exception as e: print(e)
print("\n== strategy_accounts_meta ==")
try:
    for r in led.execute("SELECT * FROM strategy_accounts_meta").fetchall():
        print(dict(r))
except Exception as e: print(e)

# 3) IC 趋势
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sig.row_factory = sqlite3.Row
for t in ['ic_daily','fusion_ic_daily','cmmr_ic_daily','center_dual_ic_daily','ic_window','ic_shadow_442']:
    try:
        tabs=[x[0] for x in sig.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if t not in tabs:
            print(f"\n== {t}: 表不存在 =="); continue
        cols=[c[1] for c in sig.execute(f"PRAGMA table_info({t})")]
        print(f"\n== {t} cols: {cols}")
        n = sig.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        dcol = 'signal_date' if 'signal_date' in cols else cols[0]
        for r in sig.execute(f"SELECT * FROM {t} ORDER BY {dcol} DESC LIMIT 12").fetchall():
            print(dict(r))
    except Exception as e:
        print(f"\n== {t} err:", e)