import sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('signals.db')
def q(sql, args=()):
    try: return c.execute(sql, args).fetchall()
    except Exception as e: return [("ERR", str(e)[:80])]

print("== ic_daily 近12信号日 (signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, ic_final) ==")
for r in reversed(q("SELECT signal_date, ROUND(ic_fusion,4), ROUND(ic_reg10,4), ROUND(ic_reg20,4), ROUND(ic_reg40,4), ROUND(ic_final,4), sample_size FROM ic_daily ORDER BY signal_date DESC LIMIT 12")):
    print(r)
print("\n== fusion_ic_daily 近10 (中枢版IC) ==")
for r in reversed(q("SELECT date, ROUND(ic,4), samples, ROUND(win_rate,3) FROM fusion_ic_daily ORDER BY date DESC LIMIT 10")):
    print(r)
print("\n== center_dual_ic_daily 近10 ==")
for r in reversed(q("SELECT date, ROUND(ic,4), samples, ROUND(top_ret,3), ROUND(bottom_ret,3) FROM center_dual_ic_daily ORDER BY date DESC LIMIT 10")):
    print(r)
print("\n== ic_window 近10 (ic_center_w10, ic_dual_w10, ic_cmmr_w10, ic_cmmrf_w10) ==")
for r in reversed(q("SELECT signal_date, ROUND(ic_center_w10,4), ROUND(ic_dual_w10,4), ROUND(ic_cmmr_w10,4), ROUND(ic_cmmrf_w10,4), ROUND(ic_reg10_w10,4) FROM ic_window ORDER BY signal_date DESC LIMIT 10")):
    print(r)
print("\n== cmmr_ic_daily 近8 ==")
for r in reversed(q("SELECT date, ROUND(ic,4), samples FROM cmmr_ic_daily ORDER BY date DESC LIMIT 8")):
    print(r)
c.close()
