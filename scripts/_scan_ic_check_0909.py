import sqlite3, statistics as st, shutil, os, tempfile

db = "/Users/zantao/.hermes/stockdb/signals.db"
print("db:", db)

# WAL 库可能被写进程持有，ro 打不开就拷副本
try:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("SELECT 1 FROM ic_daily LIMIT 1")
except Exception:
    d = tempfile.mkdtemp()
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(db + suf):
            shutil.copy2(db + suf, d + "/" + os.path.basename(db) + suf)
    conn = sqlite3.connect(os.path.join(d, os.path.basename(db)))

rows = conn.execute(
    "SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, sample_size, top_ret, bottom_ret "
    "FROM ic_daily ORDER BY signal_date DESC LIMIT 15").fetchall()
print("signal_date  fusion   reg10    reg20    reg40    n     top10%  bot10%")
for r in rows:
    f = lambda v: f"{v:+.4f}" if v is not None else "  None"
    print(f"{r[0]}  {f(r[1])} {f(r[2])} {f(r[3])} {f(r[4])}  {r[5]}  {r[6]:+.2f}  {r[7]:+.2f}")

ics = conn.execute(
    "SELECT ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20"
).fetchall()
t = list(zip(*ics))
print("\n近20日滚动均值 fusion/reg10/reg20/reg40:",
      [round(st.mean(c), 4) for c in t], f"n={len(ics)}")

# 各链最新日期
for t_ in ("cmmr_ic_daily", "fusion_ic_daily", "factor_group_ic_daily", "etf_ic", "center_dual_ic_daily", "ic_window", "factor_ic_roll"):
    try:
        dcol = "signal_date" if t_ != "factor_group_ic_daily" else "as_of_date"
        try:
            mx = conn.execute(f"SELECT MAX({dcol}) FROM {t_}").fetchone()[0]
        except Exception:
            mx = conn.execute(f"SELECT MAX(date) FROM {t_}").fetchone()[0]
        print(t_, "最新=", mx)
    except Exception as e:
        print(t_, "ERR", e)