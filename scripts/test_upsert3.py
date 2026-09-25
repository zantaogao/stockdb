#!/usr/bin/env python3
import tushare as ts
import json
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
with open(BASE / 'config.json') as f:
    cfg = json.load(f)
ts.set_token(cfg.get('tushare_token',''))
pro = ts.pro_api()

df = pro.moneyflow(ts_code='', start_date='20260701', end_date='20260701')
print(f'trade_date dtype: {df["trade_date"].dtype}')
print(f'trade_date head: {df["trade_date"].head(5).tolist()}')
print(f'trade_date type of first: {type(df["trade_date"].iloc[0])}')

# 测试不同方式
print()
print('=== str[:4] ===')
print(df['trade_date'].str[:4].head(5).tolist())

print()
print('=== astype(str)[:4] ===')
s = df['trade_date'].astype(str)
print(s.head(5).tolist())
print(s.str[:4].head(5).tolist())

print()
print('=== apply(str) ===')
print(df['trade_date'].apply(str).head(5).tolist())
