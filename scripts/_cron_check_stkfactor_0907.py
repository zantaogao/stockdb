import duckdb, sqlite3, os, time

base = os.path.expanduser("~/.hermes/stockdb")
con = duckdb.connect(f"{base}/tushare.db", read_only=True)
print("stk_factor recent:", con.execute("SELECT trade_date, count(*) FROM stk_factor WHERE trade_date>='20260901' GROUP BY 1 ORDER BY 1").fetchall())
print("stk_factor MAX:", con.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0])
print("daily MAX:", con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
con.close()

s = sqlite3.connect(f"file:{base}/signals.db?mode=ro", uri=True, timeout=10)
print("fusion_3f recent:", s.execute("SELECT replace(date,'-',''), count(*) FROM fusion_3f_signals WHERE date>='2026-09-01' GROUP BY 1 ORDER BY 1").fetchall())
s.close()

# lock/temp files present?
for f in os.listdir(base):
    if f.endswith(("-wal", "-shm", "-tmp", ".tmp", ".tmp.swp", "tmp.swp")) or "swp" in f or f.endswith(".tmp"):
        st = os.stat(os.path.join(base, f))
        print("tempfile:", f, st.st_size, time.strftime("%F %T", time.localtime(st.st_mtime)))