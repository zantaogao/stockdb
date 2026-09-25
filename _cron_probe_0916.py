import duckdb, sqlite3, json
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("TUSHARE TABLES:", tabs)
for t in ['index_daily_raw','sw_daily_raw','stock_industry_raw','daily']:
    if t in tabs:
        cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
        print(f"-- {t} cols:", cols[:40])
con.close()
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
st = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("SIGNALS TABLES:", st)
for t in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','ic_window','ic_shadow_442']:
    if t in st:
        cols = [r[1] for r in s.execute(f"PRAGMA table_info({t})").fetchall()]
        print(f"-- {t} cols:", cols)
s.close()
l = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
lt = [r[0] for r in l.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("LEDGER TABLES:", lt)
if 'strategy_accounts_meta' in lt:
    cols=[r[1] for r in l.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()]
    print("-- meta cols:", cols)
    for r in l.execute("SELECT * FROM strategy_accounts_meta").fetchall():
        print("META:", str(r)[:400])
l.close()
