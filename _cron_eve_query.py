#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘后报告补充查询（只读）"""
import sqlite3, duckdb, json, os
DB = '/Users/zantao/.hermes/stockdb'

td = duckdb.connect(os.path.join(DB, 'tushare.db'), read_only=True)

print('===== 指数近5日 =====')
for ts in ('000852.SH','000001.SH'):
    try:
        rows = td.execute("SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5", [ts]).fetchall()
        print(ts, rows[::-1])
    except Exception as e:
        print(ts, 'ERR', e)

print('===== 最近交易日列表（用于重评剩余天数核对）=====')
dts = td.execute("SELECT trade_date FROM (SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260901' ORDER BY trade_date) LIMIT 30").fetchall()
print([d[0] for d in dts])

led = sqlite3.connect(os.path.join(DB, 'ledger.db'))
led.row_factory = sqlite3.Row
print('===== 主账户持仓距止损/目标 =====')
try:
    cols = [r[1] for r in led.execute('PRAGMA table_info(holdings)')]
    print('holdings cols:', cols)
    for r in led.execute('SELECT * FROM holdings').fetchall():
        print(dict(r))
except Exception as e:
    print('ERR', e)

print('===== watchlist =====')
try:
    cols = [r[1] for r in led.execute('PRAGMA table_info(watchlist)')]
    print('watchlist cols:', cols)
    for r in led.execute('SELECT * FROM watchlist LIMIT 15').fetchall():
        print(dict(r))
except Exception as e:
    print('ERR', e)

print('===== strategy_accounts_meta =====')
try:
    for r in led.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'strategy%'").fetchall():
        print(r[0])
    rows = led.execute("SELECT * FROM strategy_accounts_meta").fetchall()
    for r in rows:
        print(tuple(r))
except Exception as e:
    print('ERR', e)

print('===== 分模型IC 近10信号日 =====')
sig = sqlite3.connect(os.path.join(DB, 'signals.db'))
sig.row_factory = sqlite3.Row
for t in ('ic_daily','fusion_ic_daily','cmmr_ic_daily','center_dual_ic_daily','ic_shadow_442'):
    try:
        cols = [c[1] for c in sig.execute(f'PRAGMA table_info({t})')]
        print(f'--- {t} cols:', cols)
        dcol = 'signal_date' if 'signal_date' in cols else ('date' if 'date' in cols else cols[0])
        for r in sig.execute(f'SELECT * FROM {t} ORDER BY {dcol} DESC LIMIT 10').fetchall():
            print(dict(r))
    except Exception as e:
        print(t, 'ERR', e)
try:
    cols = [c[1] for c in sig.execute('PRAGMA table_info(ic_window)')]
    print('--- ic_window cols:', cols)
    for r in sig.execute('SELECT * FROM ic_window ORDER BY rowid DESC LIMIT 20').fetchall():
        print(dict(r))
except Exception as e:
    print('ic_window ERR', e)

print('===== opinion_universe 概要 =====')
try:
    u = json.load(open(os.path.join(DB,'analysis/opinion_universe.json')))
    print('keys:', list(u.keys())[:20] if isinstance(u,dict) else type(u))
    if isinstance(u,dict):
        for k,v in u.items():
            if isinstance(v,dict): print(k, list(v.keys())[:8])
            elif isinstance(v,list): print(k, 'list', len(v))
except Exception as e:
    print('ERR', e)