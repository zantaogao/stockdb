#!/usr/bin/env python3
import tushare as ts
import json
from pathlib import Path
import duckdb
import pandas as pd

BASE = Path.home() / '.hermes' / 'stockdb'
with open(BASE / 'config.json') as f:
    cfg = json.load(f)
ts.set_token(cfg.get('tushare_token',''))
pro = ts.pro_api()

df = pro.moneyflow(ts_code='', start_date='20260701', end_date='20260701')
print(f'Raw rows: {len(df)}')

df['stock_code'] = df['ts_code'].str.split('.').str[0]
df['date'] = df['trade_date'].str[:4] + '-' + df['trade_date'][4:6] + '-' + df['trade_date'][6:8]
df['main_net'] = -((df['buy_elg_amount'] - df['sell_elg_amount']) + (df['buy_lg_amount'] - df['sell_lg_amount']))
df['retail_net'] = -(df['buy_sm_amount'] - df['sell_sm_amount'])
df['main_pct'] = df['main_net'] / df['net_mf_amount'].abs().replace(0, 1) * 100

cols = ['stock_code', 'date', 'main_net', 'retail_net', 'main_pct']
df = df[[c for c in cols if c in df.columns]]
df = df.dropna(subset=['date'])

print(f'After processing: {len(df)} rows')
print(f'date dtype: {df["date"].dtype}')
print(f'date sample: {df["date"].head(3).tolist()}')

c = duckdb.connect(str(BASE / 'stock.db'))
schema = c.execute('PRAGMA table_info(money_flow)').fetchall()
print(f'schema: {schema}')

min_d = str(df['date'].min())
max_d = str(df['date'].max())
print(f'DELETE range: [{min_d}, {max_d}]')

cnt = c.execute('SELECT COUNT(*) FROM money_flow WHERE date >= ? AND date <= ?', [min_d, max_d]).fetchone()[0]
print(f'Existing rows in range: {cnt}')

c.execute('DELETE FROM money_flow WHERE date >= ? AND date <= ?', [min_d, max_d])
print(f'DELETE affected: {c.rowcount}')

try:
    c.execute('INSERT INTO money_flow SELECT * FROM df')
    print(f'INSERT OK, rowcount: {c.rowcount}')
except Exception as e:
    print(f'INSERT ERROR: {e}')

c.close()
