#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查各策略账户最新净值日（只读）。"""
import sqlite3, os

base = os.path.expanduser("~/.hermes/stockdb")
c = sqlite3.connect("file:%s/ledger.db?mode=ro" % base, uri=True)

print("=== meta ===")
for r in c.execute("SELECT account_id, name, initial_capital, cash, updated_at FROM strategy_accounts_meta ORDER BY account_id"):
    print(r)

print("\n=== legacy NAV 最新5日/账户 ===")
rows = c.execute("""SELECT account_id, MAX(date) mx, COUNT(*) n FROM strategy_accounts_legacy GROUP BY account_id ORDER BY account_id""").fetchall()
for r in rows:
    print(r)

print("\n=== 每账户最后3条 ===")
for (aid,) in c.execute("SELECT DISTINCT account_id FROM strategy_accounts_legacy ORDER BY account_id"):
    for r in c.execute("SELECT date, nav, daily_ret, n_pos FROM strategy_accounts_legacy WHERE account_id=? ORDER BY date DESC LIMIT 3", (aid,)):
        print(aid, r)

print("\n=== positions 分布 ===")
for r in c.execute("SELECT account_id, COUNT(*), MAX(updated_at) FROM strategy_positions GROUP BY account_id ORDER BY account_id"):
    print(r)

print("\n=== account_balance ===")
for r in c.execute("SELECT * FROM account_balance"):
    print(r)

print("\n=== crash_state / cooldown / tp_ban ===")
for t in ("strategy_crash_state", "trade_cooldown", "trade_tp_ban"):
    try:
        print(t, c.execute("SELECT * FROM %s" % t).fetchall()[-8:])
    except Exception as e:
        print(t, "ERR", e)
c.close()
