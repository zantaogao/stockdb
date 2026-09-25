import duckdb, sqlite3, json, os
os.chdir('/Users/zantao/.hermes/stockdb')

# 1) index 5-day trend
dd = duckdb.connect('tushare.db', read_only=True)
print("== index_daily_raw last5 ==")
for r in dd.execute("""SELECT ts_code, trade_date, close, pct_chg FROM index_daily_raw
  WHERE ts_code IN ('000852.SH','000001.SH') AND trade_date>='20260824'
  ORDER BY ts_code, trade_date""").fetchall():
    print(r)

# count trading days for rebalance windows
latest = dd.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print("latest trade_date:", latest)

# 2) ledger: holdings stop/target distance
lc = sqlite3.connect('ledger.db')
lc.row_factory = sqlite3.Row
print("\n== holdings (stop/target) ==")
cols = [r[1] for r in lc.execute("PRAGMA table_info(holdings)").fetchall()]
print("cols:", cols)
for r in lc.execute("SELECT * FROM holdings").fetchall():
    d = dict(zip(cols, tuple(r)))
    print(d)

print("\n== strategy_accounts_meta ==")
mcols = [r[1] for r in lc.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()]
print("cols:", mcols)
for r in lc.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    print(dict(zip(mcols, tuple(r))))

# 3) IC series
sc = sqlite3.connect('signals.db')
sc.row_factory = sqlite3.Row
for t in ['ic_daily','fusion_ic_daily','cmmr_ic_daily','center_dual_ic_daily','ic_window']:
    try:
        cols=[r[1] for r in sc.execute(f"PRAGMA table_info({t})").fetchall()]
        print(f"\n== {t} cols:", cols)
        rows = sc.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 12").fetchall()
        for r in rows: print(dict(zip(cols, tuple(r))))
    except Exception as e:
        print(f"\n== {t} ERR {e}")

# trading days between given dates
def tdays(a,b):
    return dd.execute("SELECT COUNT(*) FROM daily WHERE trade_date>? AND trade_date<=?",[a,b]).fetchone()[0]
print("\ntrading days after 20260903:", tdays('20260903', latest))