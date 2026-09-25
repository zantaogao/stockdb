import duckdb, sqlite3
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tabs = [r[0] for r in d.execute("SHOW TABLES").fetchall() if 'etf' in r[0].lower() or 'nav' in r[0].lower() or 'fund' in r[0].lower()]
print('duckdb candidate tables:', tabs)
for t in tabs:
    cols = [c[1] for c in d.execute(f"DESCRIBE {t}").fetchall()]
    dcol = 'trade_date' if 'trade_date' in cols else ('nav_date' if 'nav_date' in cols else ('scan_date' if 'scan_date' in cols else cols[0]))
    try:
        print(t, '|', dcol, '=', d.execute(f"SELECT MAX({dcol}) FROM {t}").fetchone()[0])
    except Exception as e:
        print(t, 'ERR', e)
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('etf_scores scan_date dist:', s.execute("SELECT scan_date, COUNT(*) FROM etf_scores GROUP BY 1 ORDER BY 1 DESC LIMIT 3").fetchall())
