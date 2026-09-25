"""验证 fin 表 probe 跳过逻辑（2026-08-10 优化）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))

import tushare as ts
import duckdb

pro = ts.pro_api()
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

for table, api_fn in [('fin_balancesheet', pro.balancesheet), ('fin_cashflow', pro.cashflow)]:
    latest_end = db.execute(f'SELECT MAX(end_date) FROM {table}').fetchone()[0]
    probe = api_fn(ts_code='000001.SZ', start_date='20250101', end_date='20261231')
    latest_period = str(probe['end_date'].max())[:10].replace('-', '') if probe is not None and len(probe) > 0 else None
    skip = latest_end and latest_period and str(latest_end).replace('-', '') >= latest_period
    print(f'{table}: 本地最新报告期={latest_end}, API 最新报告期={latest_period}, 跳过={skip}')
db.close()
