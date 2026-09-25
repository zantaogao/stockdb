#!/usr/bin/env python3
"""09-16 09:45 cmmr 取价失败核查：确认是瞬时抖动还是结构性问题。"""
import sqlite3, sys, os, time
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
from core.prices import fetch_prices_batch, fetch_price_live
import duckdb

LED = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'))

print("=== 1) cmmr 账户当前持仓/目标规模 ===")
try:
    rows = LED.execute("SELECT COUNT(*) FROM strategy_positions WHERE account_id='cmmr'").fetchone()
    print("cmmr strategy_positions:", rows[0])
except Exception as e:
    print("strategy_positions err:", e)
for t in ('strategy_accounts', 'strategy_trade_log'):
    try:
        print(t, "cols:", [r[1] for r in LED.execute(f"PRAGMA table_info({t})").fetchall()][:20])
    except Exception as e:
        print(t, "err", e)

print("\n=== 2) 今日 trade_log 最近 12 笔 ===")
try:
    cur = LED.execute("SELECT * FROM trade_log WHERE replace(date,'-','')='20260916' ORDER BY rowid DESC LIMIT 12")
    cols = [d[0] for d in cur.description]
    print(cols)
    for r in cur.fetchall():
        print(r)
except Exception as e:
    print("trade_log err:", e)

print("\n=== 3) cmmr 持仓明细（若有） ===")
try:
    cur = LED.execute("SELECT code, shares, cost, buy_date FROM strategy_positions WHERE account_id='cmmr' LIMIT 30")
    for r in cur.fetchall():
        print(r)
except Exception as e:
    print("err:", e)

print("\n=== 4) 取价抖动实测：小批量 8 只 x 6 次 ===")
codes = ['000001', '600000', '603186', '300328', '600076', '600785', '001268', '003018']
fails = 0
for i in range(6):
    try:
        r = fetch_prices_batch(codes)
    except Exception as e:
        r = {}
        print("  exception:", e)
    ok = len(r or {})
    if ok == 0:
        fails += 1
    print(f"  try{i+1}: got {ok}/{len(codes)}")
    time.sleep(1)
print(f"小批量失败率: {fails}/6")

print("\n=== 5) 单票 fetch_price_live x6 ===")
for i in range(6):
    px, chg = fetch_price_live('000001')
    print(f"  try{i+1}: px={px} chg={chg}")
    time.sleep(1)

print("\n=== 6) 是否有其它 tick 异常：检查 lock ===")
print("lockdir exists:", os.path.isdir('/tmp/strategy_accounts_daily.lock'))
