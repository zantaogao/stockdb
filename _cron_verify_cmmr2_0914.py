import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('signals.db')
print("fusion_ic_daily 09-11:", c.execute("SELECT date,ic,samples,win_rate,forward_days FROM fusion_ic_daily WHERE date='2026-09-11'").fetchone())
print("fusion_ic_daily latest 3:", c.execute("SELECT date,ic,samples,win_rate,forward_days FROM fusion_ic_daily ORDER BY date DESC LIMIT 3").fetchall())
print("ic_window cmmr (calc=20260914) latest 3:")
for r in c.execute("SELECT signal_date, ic_cmmr_w10, ic_cmmrf_w10, ic_3f_w10, ic_center_w10 FROM ic_window WHERE calc_date='20260914' ORDER BY signal_date DESC LIMIT 3").fetchall():
    print("  ", r)
print("cmmr 20d finalized latest 3:", c.execute("SELECT date,ic,samples,win_rate FROM cmmr_ic_daily WHERE forward_days=20 ORDER BY date DESC LIMIT 3").fetchall())
print("cmmrf 20d finalized latest 3:", c.execute("SELECT date,ic,samples,win_rate FROM fusion_ic_daily WHERE forward_days=20 ORDER BY date DESC LIMIT 3").fetchall())
