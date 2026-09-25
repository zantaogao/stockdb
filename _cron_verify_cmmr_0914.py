import sqlite3, os, datetime
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
print("now:", datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
c = sqlite3.connect('signals.db')
print("etf_scores max(updated_at)=", c.execute("SELECT MAX(updated_at), COUNT(*) FROM etf_scores").fetchone())
print("cmmr_ic_daily date=2026-09-11:", c.execute("SELECT date,ic,samples,win_rate,forward_days FROM cmmr_ic_daily WHERE date='2026-09-11'").fetchone())
print("fusion_ic_daily date=2026-09-11:", c.execute("SELECT * FROM fusion_ic_daily WHERE signal_date='2026-09-11'").fetchone())
print("ic_window cmmr cols (calc 20260914):")
for r in c.execute("SELECT signal_date, ic_cmmr_w10, ic_cmmrf_w10, ic_3f_w10, ic_center_w10 FROM ic_window WHERE calc_date='20260914' ORDER BY signal_date DESC LIMIT 5").fetchall():
    print("  ", r)
d = c.execute("SELECT MAX(date) FROM cmmr_ic_daily").fetchone()
print("cmmr_ic_daily max date:", d)
