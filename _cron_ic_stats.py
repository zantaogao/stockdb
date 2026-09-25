import sqlite3, statistics as st
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print("== ic_daily 近10信号日 分模型 ==")
rows = sig.execute("SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall()
for r in rows: print(r)
for name in ('reg10','reg20','reg40','fusion'):
    vals = [r[{'reg10':1,'reg20':2,'reg40':3,'fusion':4}[name]] for r in rows if r[{'reg10':1,'reg20':2,'reg40':3,'fusion':4}[name]] is not None]
    last5 = vals[:5]
    print(f"{name}: 近5均值 {st.mean(last5):+.3f} 近10均值 {st.mean(vals):+.3f} 正天数(近5) {sum(1 for v in last5 if v>0)}/5")
print("== cmmr / cmmr+ / center 近10 ==")
for t in ('cmmr_ic_daily','fusion_ic_daily','center_dual_ic_daily'):
    rows = sig.execute(f"SELECT date, ic FROM {t} ORDER BY date DESC LIMIT 10").fetchall()
    vals=[r[1] for r in rows]
    print(t, [f"{d}:{v:+.3f}" for d,v in reversed(rows)])
    print(f"  {t} 近5均值 {st.mean(vals[:5]):+.3f} 近10均值 {st.mean(vals):+.3f} 正天数(近5) {sum(1 for v in vals[:5] if v>0)}/5")
# ic_window cmmr_fusion column ic_cmmrf_w10 last 10
rows = sig.execute("SELECT signal_date, ic_cmmrf_w10, ic_center_w10, ic_dual_w10 FROM ic_window WHERE ic_cmmrf_w10 IS NOT NULL ORDER BY signal_date DESC LIMIT 10").fetchall()
print("== ic_window CMMR+/中枢/dual w10 ==")
for d,c,ce,du in reversed(rows): print(d, f"cmmrf={c:+.3f} center={ce:+.3f} dual={du:+.3f}")
for i,nm in ((1,'cmmrf'),(2,'center'),(3,'dual')):
    vals=[r[i] for r in rows]
    print(f"{nm} 近5均值 {st.mean(vals[:5]):+.3f} 正天数 {sum(1 for v in vals[:5] if v>0)}/5")