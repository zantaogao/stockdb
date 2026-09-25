#!/usr/bin/env python3
# 只读核查：TDX 分钟线归档 + 聚合特征最新日期（20260914 同步后）
import duckdb, sqlite3, os, datetime

base = os.path.expanduser("~/.hermes/stockdb")
db = os.path.join(base, "tdx_archive.db")
con = duckdb.connect(db, read_only=True)
print("== tdx_archive.db ==", datetime.datetime.fromtimestamp(os.path.getmtime(db)))
for t in ["min1_archive", "min5_archive"]:
    r = con.execute(f"SELECT COUNT(*), COUNT(DISTINCT date), MIN(date), MAX(date) FROM {t}").fetchone()
    print(f"{t}: rows={r[0]:,} days={r[1]} {r[2]}~{r[3]}")
    print("   recent:", con.execute(
        f"SELECT date, COUNT(*), COUNT(DISTINCT code) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 3").fetchall())
con.close()

sdb = os.path.join(base, "signals.db")
c = sqlite3.connect(sdb)
print("== signals.db ==", datetime.datetime.fromtimestamp(os.path.getmtime(sdb)))
tabs = [x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'tdx%'").fetchall()]
print("tdx tables:", tabs)
for t in tabs:
    try:
        r = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date) FROM {t}").fetchone()
        print(f"{t}: rows={r[0]:,} days={r[1]} {r[2]}~{r[3]}")
        print("   recent:", c.execute(
            f"SELECT trade_date, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 3").fetchall())
    except Exception as e:
        print(t, "ERR", e)
c.close()
