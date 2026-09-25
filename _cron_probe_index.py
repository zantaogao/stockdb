#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测 tushare index_daily 8/14 数据是否已出 + 本地配置"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb/scripts'))
try:
    import tushare as ts
    print("tushare:", ts.__version__)
except Exception as e:
    print("tushare import fail:", e)
    sys.exit(1)

# token 来源：环境变量或本地配置
tok = os.environ.get('TUSHARE_TOKEN')
if not tok:
    # 尝试从 update_tushare_api.py 里找 token 初始化
    import re
    src = open(os.path.expanduser('~/.hermes/stockdb/scripts/update_tushare_api.py')).read()
    m = re.search(r"ts\.set_token\(['\"]([^'\"]+)['\"]\)", src)
    if m:
        tok = m.group(1)
if not tok:
    print("未找到 token")
    sys.exit(1)

ts.set_token(tok)
pro = ts.pro_api()
for code in ['000001.SH', '000300.SH', '899050.BJ']:
    try:
        df = pro.index_daily(ts_code=code, start_date='20260813', end_date='20260814')
        print(f"{code}: {len(df)} 行, 日期={list(df['trade_date']) if len(df) else '无'}")
    except Exception as e:
        print(f"{code}: ERROR {str(e)[:100]}")
