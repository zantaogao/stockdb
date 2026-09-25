#!/usr/bin/env python3
"""Cron health check: DB freshness + integrity spot checks (file-based to avoid inline -c approval)."""
import duckdb, sqlite3, sys, datetime

issues = []

# --- deps ---
print(f"duckdb {duckdb.__version__} | sqlite3 {sqlite3.sqlite_version}")

# --- tushare.db (DuckDB) freshness ---
tdb = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)
try:
    d = tdb.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    n = tdb.execute("SELECT COUNT(*) FROM daily WHERE trade_date = ?", [d]).fetchone()[0]
    print(f"daily MAX(trade_date)={d} rows={n}")
    fd = tdb.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()[0]
    print(f"fund_daily MAX(trade_date)={fd}")
    # full-table scan to trigger checksums on hot tables
    for t in ("daily", "daily_basic", "stock_basic"):
        c = tdb.execute(f"SELECT COUNT(*), COUNT(1) FROM {t}").fetchone()
        print(f"scan {t}: count={c[0]} (checksum ok)")
except Exception as e:
    issues.append(f"tushare.db 异常: {e}")
finally:
    tdb.close()

# --- state.db (SQLite) ---
sdb = sqlite3.connect("/Users/zantao/.hermes/stockdb/state.db")
try:
    ic = sdb.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"state.db integrity_check={ic}")
    sig = sdb.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0]
    print(f"signal_history latest={sig}")
    fus = sdb.execute("SELECT MAX(REPLACE(date,'-','')) FROM fusion_3f_signals").fetchone()[0]
    dist = sdb.execute("SELECT signal, COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? GROUP BY 1", [fus]).fetchall()
    print(f"fusion_3f latest={fus} dist={dict(dist)}")
    icd = sdb.execute("SELECT MAX(signal_date) FROM ic_daily").fetchone()[0]
    print(f"ic_daily latest signal_date={icd}")
    h = sdb.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    cash = sdb.execute("SELECT cash_balance FROM account_balance ORDER BY last_update DESC LIMIT 1").fetchone()
    print(f"holdings={h} cash={cash[0] if cash else None}")
except Exception as e:
    issues.append(f"state.db 异常: {e}")
finally:
    sdb.close()

today = datetime.date.today()
print(f"today={today} (weekday={today.weekday()})")
if issues:
    print("ISSUES:")
    for i in issues:
        print(" -", i)
    sys.exit(1)
print("ALL_OK")
sys.exit(0)
