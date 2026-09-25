# -*- coding: utf-8 -*-
"""只读探查：确认表名与列结构（2026-09-15 盘后报告用）"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("== tushare.db tables ==")
for t in sorted(tabs):
    print(" ", t)

for t in ['index_daily_raw', 'sw_daily_raw', 'stock_industry_raw', 'daily_raw', 'daily', 'daily_basic']:
    if t in tabs:
        cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"\n-- {t} (rows={n})\n   {cols}")
        if t in ('index_daily_raw', 'sw_daily_raw'):
            print("   maxdate:", con.execute(f"SELECT MAX(trade_date) FROM {t}").fetchone()[0])
            print("   sample:", con.execute(f"SELECT * FROM {t} LIMIT 2").fetchall())

con.close()

print("\n== ledger.db tables ==")
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
for r in lc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    print(" ", r[0])
for t in ['holdings', 'watchlist', 'position_peaks', 'strategy_accounts_meta', 'strategy_positions', 'strategy_accounts']:
    try:
        cols = [c[1] for c in lc.execute(f"PRAGMA table_info({t})").fetchall()]
        n = lc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"\n-- {t} (rows={n})\n   {cols}")
    except Exception as e:
        print(f"\n-- {t}: {e}")
lc.close()

print("\n== signals.db tables ==")
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))
for r in sc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    print(" ", r[0])
for t in ['ic_daily', 'fusion_ic_daily', 'center_dual_ic_daily', 'ic_window']:
    try:
        cols = [c[1] for c in sc.execute(f"PRAGMA table_info({t})").fetchall()]
        n = sc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"\n-- {t} (rows={n})\n   {cols}")
    except Exception as e:
        print(f"\n-- {t}: {e}")
sc.close()
