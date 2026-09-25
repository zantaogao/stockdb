# 核实 patrol stk_factor ❌ 是否为误报：直接查活库当日行数
import time
import duckdb, sqlite3

tgt = time.strftime("%Y%m%d")
tgt_iso = time.strftime("%Y-%m-%d")
BASE = "/Users/zantao/.hermes/stockdb"

con = duckdb.connect(f"{BASE}/tushare.db", read_only=True)
n = con.execute(f"select count(*) from stk_factor where trade_date='{tgt}'").fetchone()[0]
mx = con.execute("select max(trade_date) from stk_factor").fetchone()[0]
con.close()

sc = sqlite3.connect(f"file:{BASE}/signals.db?mode=ro", uri=True, timeout=30)
n2 = sc.execute("select count(*) from fusion_3f_signals where replace(date,'-','')=?", (tgt,)).fetchone()[0]
sc.close()

print(f"today={tgt}")
print(f"stk_factor {tgt}: {n} rows (max={mx}), 阈值>=4000 -> {'OK' if n >= 4000 else 'FAIL'}")
print(f"fusion_3f_signals {tgt}: {n2} rows, 阈值>=100 -> {'OK' if n2 >= 100 else 'FAIL'}")
