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
print(f'net_mf_amount nulls: {df["net_mf_amount"].isna().sum()}')
print(f'net_mf_amount zeros: {(df["net_mf_amount"] == 0).sum()}')
print(f'net_mf_amount sample: {df["net_mf_amount"].head(5).tolist()}')

df['stock_code'] = df['ts_code'].str.split('.').str[0]
df['date'] = df['trade_date'].str[:4] + '-' + df['trade_date'][4:6] + '-' + df['trade_date'][6:8]

print(f'After date parse, date nulls: {df["date"].isna().sum()}')

df['main_net'] = -((df['buy_elg_amount'] - df['sell_elg_amount']) + (df['buy_lg_amount'] - df['sell_lg_amount']))
df['retail_net'] = -(df['buy_sm_amount'] - df['sell_sm_amount'])
df['main_pct'] = df['main_net'] / df['net_mf_amount'].abs().replace(0, 1) * 100

print(f'main_net nulls: {df["main_net"].isna().sum()}')
print(f'main_pct nulls: {df["main_pct"].isna().sum()}')

cols = ['stock_code', 'date', 'main_net', 'retail_net', 'main_pct']
df = df[[c for c in cols if c in df.columns]]
print(f'After col select, rows: {len(df)}')
print(f'date nulls: {df["date"].isna().sum()}')

df2 = df.dropna(subset=['date'])
print(f'After dropna(date), rows: {len(df2)}')

# 看看date列到底有没有nan
print(f'date head: {df["date"].head(5).tolist()}')
print(f'date isna: {df["date"].isna().head(5).tolist()}')
