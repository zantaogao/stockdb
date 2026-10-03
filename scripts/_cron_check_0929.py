import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/ledger.db')
tabs = [t[0] for t in c.execute("select name from sqlite_master where type='table'")]
print("tables:", tabs)
for t in tabs:
    cols = [x[1] for x in c.execute(f"pragma table_info({t})")]
    if any(k in cols for k in ('trade_date','date','day')):
        dcol = next(k for k in ('trade_date','date','day') if k in cols)
        try:
            n = c.execute(f"select count(*) from {t} where {dcol} in ('20260929','2026-09-29')").fetchone()[0]
            print(t, "rows_on_0929:", n)
            if n and 'side' in cols or t in ('trades','trade_log'):
                for row in c.execute(f"select * from {t} where {dcol} in ('20260929','2026-09-29') limit 20"):
                    print(" ", row)
        except Exception as e:
            print(t, "ERR", e)
