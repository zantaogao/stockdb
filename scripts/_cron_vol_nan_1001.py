import sqlite3, os, duckdb, statistics
home = os.path.expanduser('~/.hermes')
conn = sqlite3.connect(f'file:{home}/stockdb/signals.db?mode=ro', uri=True)
cols = [c[1] for c in conn.execute("PRAGMA table_info(factor_group_ic_daily)")]
print('vol表列:', cols)
# find the name/date/val cols heuristically
name_col = next((c for c in cols if c in ('factor_group','group_name','factor_name','name')), None)
date_col = next((c for c in cols if 'date' in c), None)
print('name_col=', name_col, 'date_col=', date_col)
if name_col:
    for r in conn.execute(f"SELECT * FROM factor_group_ic_daily WHERE {name_col} LIKE '%波动%' ORDER BY {date_col} DESC LIMIT 8"):
        print(r)
conn.close()

tc = duckdb.connect(f'{home}/stockdb/tushare.db', read_only=True)
print('\n近12交易日市场环境:')
for r in tc.execute("""
    SELECT trade_date, ROUND(AVG(pct_chg),2), ROUND(SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*100.0/COUNT(*),1), COUNT(*)
    FROM daily WHERE trade_date >= '20260915' GROUP BY trade_date ORDER BY trade_date
"""):
    print(' ', r[0], '均涨%+.2f%%' % r[1], '涨占比%.1f%%' % r[2], 'n=%d' % r[3])
tc.close()
