#!/usr/bin/env python3
"""cron 巡检: 策略账户日更 guard 误判核查 (2026-09-15)"""
import sqlite3, sys, json
from datetime import datetime
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.trading_time import in_trading_session
from core.prices import fetch_price_live, fetch_prices_batch

now = datetime.now()
print("now:", now.strftime('%Y-%m-%d %H:%M:%S %A'))
print("in_trading_session:", in_trading_session(now))

for code in ['000001', 'sh000001', '399001', '000300']:
    try:
        print(f"fetch_price_live({code}):", fetch_price_live(code))
    except Exception as e:
        print(f"fetch_price_live({code}) EXC:", type(e).__name__, e)

try:
    b = fetch_prices_batch(['000001', '600519', '399001', '000300'])
    print("batch keys:", list(b.keys())[:20])
    for k, v in list(b.items())[:10]:
        print("  ", k, v)
except Exception as e:
    print("batch EXC:", type(e).__name__, e)

db = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
db.row_factory = sqlite3.Row
print("\n== objects ==")
for r in db.execute("SELECT type,name FROM sqlite_master WHERE name LIKE '%strateg%' ORDER BY type,name"):
    print(" ", r['type'], r['name'])

print("\n== strategy_accounts_meta ==")
try:
    cols = [c[1] for c in db.execute("PRAGMA table_info(strategy_accounts_meta)")]
    print(" cols:", cols)
    for r in db.execute("SELECT * FROM strategy_accounts_meta LIMIT 20"):
        print("  ", dict(r))
except Exception as e:
    print(" EXC:", e)

print("\n== strategy_positions 最近变化 ==")
try:
    cols = [c[1] for c in db.execute("PRAGMA table_info(strategy_positions)")]
    print(" cols:", cols)
    for r in db.execute("SELECT * FROM strategy_positions LIMIT 5"):
        print("  ", dict(r))
except Exception as e:
    print(" EXC:", e)

print("\n== ca_run_log ==")
try:
    cols = [c[1] for c in db.execute("PRAGMA table_info(ca_run_log)")]
    print(" cols:", cols)
    for r in db.execute("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 12"):
        print("  ", dict(r))
except Exception as e:
    print(" EXC:", e)

print("\n== trade_log 最近 10 条 (策略账户) ==")
try:
    cols = [c[1] for c in db.execute("PRAGMA table_info(trade_log)")]
    print(" cols:", cols)
    for r in db.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 10"):
        print("  ", dict(r))
except Exception as e:
    print(" EXC:", e)

print("\n== ca_adjustments 最近 ==")
try:
    cols = [c[1] for c in db.execute("PRAGMA table_info(ca_adjustments)")]
    print(" cols:", cols)
    for r in db.execute("SELECT * FROM ca_adjustments ORDER BY rowid DESC LIMIT 8"):
        print("  ", dict(r))
except Exception as e:
    print(" EXC:", e)
db.close()
