#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核查3：今日成交票在策略持仓/台账中的勾稽"""
import sqlite3, os
con = sqlite3.connect(os.path.expanduser("~/.hermes/stockdb/ledger.db"))
cols = [c[1] for c in con.execute("PRAGMA table_info(strategy_positions)")]
print("strategy_positions cols:", cols)
for code in ("688217", "000592", "300299", "605598", "300274", "603307"):
    rows = con.execute("SELECT * FROM strategy_positions WHERE code=? OR ts_code=?", (code, code)).fetchall() \
        if "code" in cols else []
    print(f"  {code}: {rows if rows else 'NOT HELD'}")
print("\n每账户持仓数:")
for r in con.execute("SELECT account_id, COUNT(*) FROM strategy_positions GROUP BY account_id"):
    print("  ", r)
print("\naccount_balance(主账户):", con.execute("SELECT * FROM account_balance").fetchall())
con.close()
