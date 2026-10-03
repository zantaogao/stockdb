import sqlite3, json
conn = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro", uri=True)
c = conn.cursor()

print("=== ic_daily 近12行 (signal_date, fusion/10d/20d/40d) ===")
for r in c.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, sample_size FROM ic_daily ORDER BY signal_date DESC LIMIT 12"):
    print(r)

print("\n=== ic_daily 近20日统计 ===")
rows = c.execute("SELECT ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()
import statistics as st
for i, name in enumerate(["fusion","reg10","reg20","reg40"]):
    vals = [r[i] for r in rows if r[i] is not None]
    pos = sum(1 for v in vals if v > 0)
    print(f"{name}: n={len(vals)} 均值={st.mean(vals):+.4f} 正天数={pos}/{len(vals)} 最小={min(vals):+.4f}")

print("\n=== factor_group_ic_daily 波动组近5日 (查nan) ===")
try:
    for r in c.execute("SELECT calc_date, factor_name, ic, sample_size FROM factor_group_ic_daily WHERE factor_name LIKE '%波动%' ORDER BY calc_date DESC LIMIT 6"):
        print(r)
except Exception as e:
    print("ERR", e)

print("\n=== cmmr/fusion_ic_daily 近5行 ===")
try:
    for r in c.execute("SELECT date, ic, samples, forward_days FROM cmmr_ic_daily ORDER BY date DESC LIMIT 5"):
        print("cmmr", r)
    for r in c.execute("SELECT date, ic, samples, forward_days FROM fusion_ic_daily ORDER BY date DESC LIMIT 5"):
        print("fusion3f", r)
except Exception as e:
    print("ERR", e)

print("\n=== ic_window 最近5个信号日真窗口IC ===")
cols = [d[1] for d in c.execute("PRAGMA table_info(ic_window)")]
print("cols:", cols)
sel = [x for x in ["signal_date","ic_reg10_w10","ic_reg20_w20","ic_reg40_w40","ic_fusion_w10","ic_fusion_w20","ic_3f_w10","ic_cmmr_w10","ic_cmmrf_w10","ic_dual_w10"] if x in cols]
for r in c.execute(f"SELECT {','.join(sel)} FROM ic_window ORDER BY signal_date DESC LIMIT 6"):
    print(dict(zip(sel, r)))
conn.close()
