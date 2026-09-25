"""复现 patrol stk_factor 的 'unable to open database file'：与脚本运行时同样在 stockdb 目录下打开临时库路径。"""
import os
import duckdb

BASE = os.path.expanduser("~/.hermes/stockdb")
os.chdir(BASE)
tmp = f"{BASE}/tushare.db.new"
print("tushare.db.new exists:", os.path.exists(tmp))
try:
    con = duckdb.connect(tmp, read_only=True)
    print("duckdb ro open temp:", con.execute("select 1").fetchone())
    con.close()
except Exception as e:
    print("duckdb open FAIL:", repr(e)[:150])
