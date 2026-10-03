import sqlite3, os, statistics
cands = [os.path.expanduser(p) for p in ["~/.hermes/state.db","~/.hermes/stockdb/signals.db","~/.hermes/stockdb/ledger.db","~/.hermes/stockdb/stock.db"]]
db = None
for p in cands:
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        t = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "ic_daily" in t:
            db = p; print("ic_daily in", p); c.close(); break
        c.close()
    except Exception as e:
        print(p, "ERR", e)
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = con.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, top_ret, bottom_ret FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()
print("signal_date fusion  reg10   reg20   reg40")
for r in reversed(rows):
    print(r)
for i,name in [(1,'fusion'),(2,'reg10'),(3,'reg20'),(4,'reg40')]:
    vals = [r[i] for r in rows if r[i] is not None]
    if vals:
        print(name, "n=",len(vals), "mean=", round(statistics.mean(vals),4), "pos=", sum(1 for v in vals if v>0), "last5mean=", round(statistics.mean(vals[:5]),4) if len(vals)>=5 else None)
print("--- ic_window last 10 (if exists) ---")
try:
    for r in con.execute("SELECT signal_date, ic_reg10_w10, ic_fusion_w10, ic_fusion_w20, ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10 FROM ic_window ORDER BY signal_date DESC LIMIT 10").fetchall():
        print(r)
except Exception as e:
    try:
        for r in con.execute("SELECT * FROM ic_window ORDER BY signal_date DESC LIMIT 5").fetchall():
            print(r)
    except Exception as e2:
        print("err", e2)
con.close()
