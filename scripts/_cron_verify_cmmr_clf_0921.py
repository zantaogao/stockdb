#!/usr/bin/env python3
"""cmmr_clf 新账户选池只读验证（09-21）：直接调 get_signal_targets 两个 src 对比。"""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path.home()/'.hermes/stockdb'))
import duckdb
from scripts.strategy_accounts_daily import get_signal_targets, ACCOUNTS
state = sqlite3.connect(str(Path.home()/'.hermes/stockdb/ledger.db'))
state.execute("ATTACH DATABASE ? AS sig", (str(Path.home()/'.hermes/stockdb/signals.db'),))
tushare = duckdb.connect(str(Path.home()/'.hermes/stockdb/tushare.db'), read_only=True)
bad = set()
d = '20260921'
a = get_signal_targets(state, tushare, d, 'cmmr', bad)
b = get_signal_targets(state, tushare, d, 'cmmr_clf', bad)
print(f"母池 cmmr 候选 {len(a)} 只，头名 {a[0][0]}")
print(f"cmmr_clf 候选 {len(b)} 只，头名 {b[0][0]}")
ta = [c for c, _ in a[:10]]; tb = [c for c, _ in b[:10]]
print(f"母top10  : {ta}")
print(f"clf票top10: {tb}")
print(f"top10 重叠 {len(set(ta)&set(tb))}/10")
print("ACCOUNTS 注册确认:", 'cmmr_clf' in ACCOUNTS, ACCOUNTS['cmmr_clf'])
