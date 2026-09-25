#!/usr/bin/env python3
# 0925 成交明细 + 当前持仓（核实假跌票 001225 是否被买入）
import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=10)
rows = db.execute("""
    SELECT id, trade_date, trade_time, direction, code, name, price, quantity, strategy
    FROM trade_log WHERE trade_date = '20260925' OR trade_date = '2026-09-25'
    ORDER BY trade_time""").fetchall()
print('0925 成交', len(rows), '笔')
for r in rows:
    print(' ', r)
hold = db.execute("""SELECT code, name, shares, avg_cost, latest_price, buy_date
    FROM holdings WHERE shares > 0 ORDER BY code""").fetchall()
print('当前持仓', len(hold), '只')
for h in hold:
    print(' ', h)
