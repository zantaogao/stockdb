import duckdb, sqlite3, json, os, datetime
os.chdir('/Users/zantao/.hermes/stockdb')

# 1) index 5-day trend
td = duckdb.connect('tushare.db', read_only=True)
print("=== index_daily_raw 近5日 ===")
for r in td.execute("""SELECT ts_code, trade_date, close, pct_chg FROM index_daily_raw
  WHERE ts_code IN ('000852.SH','000001.SH') AND trade_date >= '20260901'
  ORDER BY ts_code, trade_date""").fetchall():
    print(r)

print("=== 实交易日(9月以来) ===")
days = [r[0] for r in td.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260801' ORDER BY trade_date").fetchall()]
print(days)

sig = sqlite3.connect('signals.db')
sig.text_factory = str

print("=== ic_daily 近10信号日 (10d/20d/40d) ===")
try:
    cols=[c[1] for c in sig.execute("PRAGMA table_info(ic_daily)")]
    print("cols:", cols)
    for r in sig.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall():
        print(r)
except Exception as e: print("ERR", e)

for tbl in ['fusion_ic_daily','cmmr_ic_daily','center_dual_ic_daily','ic_window']:
    print(f"=== {tbl} ===")
    try:
        cols=[c[1] for c in sig.execute(f"PRAGMA table_info({tbl})")]
        print("cols:", cols)
        dcol = 'signal_date' if 'signal_date' in cols else ('date' if 'date' in cols else cols[0])
        for r in sig.execute(f"SELECT * FROM {tbl} ORDER BY {dcol} DESC LIMIT 10").fetchall():
            print(r)
    except Exception as e: print("ERR", e)

led = sqlite3.connect('ledger.db')
led.text_factory = str
print("=== strategy_accounts_meta ===")
for r in led.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    print(r)

print("=== holdings 距止损/止盈 (join watchlist targets) ===")
try:
    cols=[c[1] for c in led.execute("PRAGMA table_info(holdings)")]
    print("holdings cols:", cols)
    cols2=[c[1] for c in led.execute("PRAGMA table_info(watchlist)")]
    print("watchlist cols:", cols2)
except Exception as e: print("ERR", e)