#!/usr/bin/env python3
"""核查 20260925 是否交易日 + trading_time 判定"""
import sys
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import duckdb
from core.trading_time import in_trading_session

tdu = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
print('tables with cal:', [r[0] for r in tdu.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_name ILIKE '%cal%'").fetchall()])
for t in ['trade_cal', 'trade_calendar']:
    try:
        r = tdu.execute(f"SELECT * FROM {t} WHERE cal_date IN ('20260923','20260924','20260925','20260928') ORDER BY cal_date").fetchall()
        if r:
            print(t, r)
    except Exception as e:
        print(t, 'ERR', e)
try:
    print('daily max date:', tdu.execute("SELECT MAX(trade_date) FROM daily").fetchone())
except Exception as e:
    print('daily err', e)
tdu.close()
print('in_trading_session():', in_trading_session())
try:
    import core.trading_time as tt
    print(open(tt.__file__).read())
except Exception as e:
    print('read err', e)
