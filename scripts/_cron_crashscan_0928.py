import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t in ('strategy_crash_state','crash_state'):
    for db in ('ledger','signals','state','stock','strategies','a_quant','aquant'):
        try:
            c2 = sqlite3.connect(f'/Users/zantao/.hermes/stockdb/{db}.db')
            r = c2.execute(f'SELECT * FROM {t}').fetchall()
            print(db, t, r)
            c2.close()
        except Exception:
            pass
# also count distinct codes 0924 in signal_history
print('distinct reg10 pool 0924:', con.execute("SELECT COUNT(DISTINCT stock_code) FROM signal_history WHERE REPLACE(date,'-','')='20260924' AND reg10 IS NOT NULL").fetchone())
print('signal_history rows 0924:', con.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260924'").fetchone())
