#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：库结构/新鲜度速查（只读）"""
import sqlite3, sys
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')

print('=== ledger.db 表 ===')
con = sqlite3.connect(str(BASE / 'ledger.db'))
for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    try:
        n = con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
    except Exception as e:
        n = 'err'
    print('  %-28s %s' % (t, n))
print('\n=== 策略账户持仓类表内容预览 ===')
for t in ('strategy_holdings', 'strategy_account', 'position_peaks', 'watchlist'):
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]
        print(' %s: %s' % (t, cols))
        for r in con.execute('SELECT * FROM "%s" LIMIT 3' % t):
            print('   ', r)
    except Exception as e:
        print(' %s err %s' % (t, e))
con.close()

print('\n=== signals.db tdx/system 表新鲜度 ===')
scon = sqlite3.connect(str(BASE / 'signals.db'))
for (t,) in scon.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    try:
        cols = [r[1] for r in scon.execute('PRAGMA table_info("%s")' % t)]
        datecol = next((c for c in ('trade_date', 'date', 'signal_date', 'trade_time', 'update_time') if c in cols), None)
        n = scon.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        mx = ''
        if datecol:
            mx = scon.execute('SELECT MAX("%s") FROM "%s"' % (datecol, t)).fetchone()[0]
        print('  %-26s n=%-8s %s=%s' % (t, n, datecol, mx))
    except Exception as e:
        print('  %s err %s' % (t, e))
scon.close()

print('\n=== tushare.db daily 最新 ===')
try:
    import duckdb
    d = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
    print(d.execute('SELECT MAX(trade_date) FROM daily').fetchone())
    d.close()
except Exception as e:
    print('duckdb err', e)
