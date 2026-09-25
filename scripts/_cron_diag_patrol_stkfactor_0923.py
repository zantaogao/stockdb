"""诊断 patrol stk_factor 的 unable to open database file：逐库逐查询定位。"""
import os, sqlite3, time
import duckdb

BASE = os.path.expanduser("~/.hermes/stockdb")
tgt = time.strftime("%Y%m%d")
tgt_iso = time.strftime("%Y-%m-%d")

for p in [f"{BASE}/tushare.db", f"{BASE}/signals.db"]:
    exists = os.path.isfile(p)
    size = os.path.getsize(p) if exists else -1
    print(f"{p} exists={exists} size={size}")
    if exists:
        with open(p, "rb") as f:
            print("  head:", f.read(16))

# test duckdb ro
try:
    con = duckdb.connect(f"{BASE}/tushare.db", read_only=True)
    n = con.execute(f"select count(*) from stk_factor where trade_date='{tgt}'").fetchone()[0]
    con.close()
    print("duckdb ok, stk_factor当日行数:", n)
except Exception as e:
    print("duckdb FAIL:", repr(e)[:200])

# test sqlite ro
try:
    con = sqlite3.connect(f"file:{BASE}/signals.db?mode=ro", uri=True, timeout=10)
    n2 = con.execute("select count(*) from fusion_3f_signals where replace(date,'-','')=?", (tgt,)).fetchone()[0]
    con.close()
    print("sqlite ok, fusion_3f当日条数:", n2)
except Exception as e:
    print("sqlite FAIL:", repr(e)[:200])
