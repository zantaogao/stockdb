#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3, os
con = sqlite3.connect(os.path.expanduser("~/.hermes/stockdb/ledger.db"))
print("今日成交票的持仓归属:")
for code in ("688217", "000592", "300299", "605598", "300274", "603307"):
    rows = con.execute("SELECT account_id, code, name, shares, avg_cost, total_cost "
                       "FROM strategy_positions WHERE code=?", (code,)).fetchall()
    print(f"  {code}: {rows if rows else 'NOT HELD'}")
print("\n每账户持仓数/总成本:")
for r in con.execute("SELECT account_id, COUNT(*), ROUND(SUM(total_cost),0) "
                     "FROM strategy_positions GROUP BY account_id ORDER BY account_id"):
    print("  ", r)
con.close()
