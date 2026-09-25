import duckdb

c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('today rows:', c.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260901'").fetchone()[0])

# What was the script actually fetching? Check the .py
src = open('/Users/zantao/.hermes/stockdb/scripts/backfill_stk_factor.py', encoding='utf-8').read()
import re
ts = sorted(set(re.findall(r'(index_daily\w*|stk_factor\w*|\.SH|\.SZ)', src)))
print('symbols in script:', ts[:20])

idx = c.execute("SELECT DISTINCT ts_code FROM index_daily_raw WHERE trade_date='20260901'").fetchall()
print('index_daily_raw today codes:', len(idx), [x[0] for x in idx])