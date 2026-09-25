#!/usr/bin/env python3
import tushare as ts
import json
from pathlib import Path
import pandas as pd

BASE = Path.home() / '.hermes' / 'stockdb'
with open(BASE / 'config.json') as f:
    cfg = json.load(f)
ts.set_token(cfg.get('tushare_token',''))
pro = ts.pro_api()

df = pro.moneyflow(ts_code='', start_date='20260701', end_date='20260701')
print(f'Raw rows: {len(df)}')
print(f'ts_code nulls: {df["ts_code"].isna().sum()}')
print(f'trade_date nulls: {df["trade_date"].isna().sum()}')

# Step by step
df['stock_code'] = df['ts_code'].str.split('.').str[0]
print(f'After stock_code, rows: {len(df)}, nulls: {df["stock_code"].isna().sum()}')

df['date'] = df['trade_date'].str[:4] + '-' + df['trade_date'][4:6] + '-' + df['trade_date'][6:8]
print(f'After date (str[:4]), rows: {len(df)}, date nulls: {df["date"].isna().sum()}')

# Try different approach
df2 = pro.moneyflow(ts_code='', start_date='20260701', end_date='20260701')
df2['date2'] = df2['trade_date'].astype(str).str[:4] + '-' + df2['trade_date'].astype(str).str[4:6] + '-' + df2['trade_date'].astype(str).str[6:8]
print(f'After date2 (astype), rows: {len(df2)}, date2 nulls: {df2["date2"].isna().sum()}')
print(f'date2 head: {df2["date2"].head(3).tolist()}')
