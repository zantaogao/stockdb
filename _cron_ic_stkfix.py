#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_ic_stkfix.py — 诊断+补拉 stk_factor 08-03 缺口 (只读诊断先行)"""
import sys, json, os, time
from pathlib import Path
BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

import duckdb
import tushare as ts

# 1. 读 token
with open(BASE / 'config.json') as f:
    cfg = json.load(f)
token = cfg.get('tushare_token', '')
ts.set_token(token)
pro = ts.pro_api()

# 2. 查 stk_factor 表 (旧表) 08-03 行数
tdb = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
for r in tdb.execute("""
    SELECT trade_date, COUNT(*) AS n FROM stk_factor
    WHERE trade_date >= '20260727' GROUP BY trade_date ORDER BY trade_date
""").fetchall():
    print(f"stk_factor {r[0]}: {r[1]} 行")
tdb.close()

# 3. 测试 API: 拉 20260803 stk_factor_pro 全量行数
print("\n== tushare API 实测 ==")
df = pro.stk_factor_pro(trade_date='20260803')
print(f"stk_factor_pro(20260803) API 返回: {0 if df is None else len(df)} 行")
if df is not None and len(df) > 0:
    print(f"  列数: {df.shape[1]}, 样例 ts_code: {df['ts_code'].head(3).tolist()}")
    print(f"  是否含 macd_dif: {'macd_dif' in df.columns}")

# 4. 对照: 拉 20260731 (正常日) 行数做基准
df2 = pro.stk_factor_pro(trade_date='20260731')
print(f"stk_factor_pro(20260731) API 返回: {0 if df2 is None else len(df2)} 行 (基准)")
