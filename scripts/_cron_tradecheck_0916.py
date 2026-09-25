#!/usr/bin/env python3
"""今日策略脚本落库明细（排除 agent_auto 独立执行），确认 09:45 拍只改了 reg10_solo 一笔。"""
import sqlite3, os
LED = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'))
print("=== 今日 trade_log 按 strategy/direction 汇总 ===")
for r in LED.execute("""SELECT strategy, direction, COUNT(*), ROUND(SUM(amount),0)
                        FROM trade_log WHERE replace(trade_date,'-','')='20260916'
                        GROUP BY 1,2 ORDER BY 1,2"""):
    print(r)
print("\n=== 09:40 之后的非 agent_auto 成交 ===")
for r in LED.execute("""SELECT id, trade_date, trade_time, strategy, direction, code, name, quantity, price, notes
                        FROM trade_log
                        WHERE replace(trade_date,'-','')='20260916' AND trade_time >= '09:40'
                          AND strategy <> 'agent_auto' ORDER BY id"""):
    print(r)
print("\n=== 今日 strategy_accounts 行数（应每账户 1 行/日） ===")
for r in LED.execute("""SELECT account_id, COUNT(*) FROM strategy_accounts
                        WHERE replace(date,'-','')='20260916' GROUP BY 1"""):
    print(r)
