"""确认数据本身健康：用 duckdb 只读打开 signals.db 查当日数据；并复现 WAL 假设。"""
import os, sqlite3
import duckdb

BASE = os.path.expanduser("~/.hermes/stockdb")
tgt = "20260923"
p = f"{BASE}/signals.db"

# journal mode 确认
con = sqlite3.connect(p)  # rw 打开（只读查询，不改数据）
jm = con.execute("pragma journal_mode").fetchone()[0]
print("journal_mode =", jm)
n = con.execute("select count(*) from fusion_3f_signals where replace(date,'-','')=?", (tgt,)).fetchone()[0]
n_fc = con.execute("select count(*) from fusion_center_signals where replace(date,'-','')=?", (tgt,)).fetchone()[0]
n_nf = con.execute("select max(trade_date) from new_factors").fetchone()[0]
con.close()
print(f"fusion_3f_signals {tgt}: {n} 条 | fusion_center_signals {tgt}: {n_fc} 条 | new_factors MAX={n_nf}")

# 验证假设：readonly 打开失败 vs immutable 可开
try:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    con.execute("select 1").fetchone()
    print("mode=ro: OK")
    con.close()
except Exception as e:
    print("mode=ro FAIL:", repr(e)[:80])
try:
    con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True, timeout=10)
    con.execute("select 1").fetchone()
    print("mode=ro&immutable=1: OK")
    con.close()
except Exception as e:
    print("immutable FAIL:", repr(e)[:80])
