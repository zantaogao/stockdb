#!/usr/bin/env python3
"""验证 strategy_accounts_daily.py v2 执行端（top20 边界 + 重评判定）"""
import sqlite3, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from scripts.strategy_accounts_daily import get_signal_targets
import duckdb

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tushare = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
d = '20260803'
for src in ['fusion_3f', 'cmmr', 'cmmr_fusion']:
    t10 = get_signal_targets(state, tushare, d, src, set(), top_n=10)
    t20 = get_signal_targets(state, tushare, d, src, set(), top_n=20)
    overlap = len(set(c for c, _ in t10) & set(c for c, _ in t20))
    print(f'{src}: top10={len(t10)} 只, top20={len(t20)} 只, 重合={overlap}')
