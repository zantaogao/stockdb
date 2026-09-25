import sqlite3
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print("== ic_daily 近10信号日 (reg10/20/40/fusion) ==")
for r in s.execute("SELECT signal_date,ic_reg10,ic_reg20,ic_reg40,ic_fusion,sample_size FROM ic_daily ORDER BY signal_date DESC LIMIT 10"):
    print(r)
print("== ic_window 近10 ==")
for r in s.execute("SELECT signal_date,ic_reg10_w10,ic_reg20_w20,ic_reg40_w40,ic_fusion_w10,ic_cmmr_w10,ic_cmmrf_w10,ic_center_w10,ic_dual_w10,n FROM ic_window ORDER BY signal_date DESC LIMIT 10"):
    print(r)
print("== cmmr_ic_daily 近8 ==")
for r in s.execute("SELECT date,ic,samples,win_rate FROM cmmr_ic_daily ORDER BY date DESC LIMIT 8"):
    print(r)
print("== center_dual_ic_daily 近8 ==")
for r in s.execute("SELECT date,fwd10_top10,fwd20_top10 FROM center_dual_ic_daily ORDER BY date DESC LIMIT 8"):
    print(r)
print("== fusion_ic_daily 近8 ==")
for r in s.execute("SELECT date,ic,samples,win_rate FROM fusion_ic_daily ORDER BY date DESC LIMIT 8"):
    print(r)
