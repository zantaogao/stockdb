import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('signals.db')
print("== cmmr_ic_daily latest 12 ==")
for r in c.execute("SELECT date, ic, samples, positive_days, win_rate, forward_days FROM cmmr_ic_daily ORDER BY date DESC LIMIT 12").fetchall():
    print(r)
print("\n== cmmr_ic_daily count by date (last 8 distinct dates) ==")
for r in c.execute("SELECT date, COUNT(*), SUM(forward_days=20), SUM(forward_days=1) FROM cmmr_ic_daily GROUP BY date ORDER BY date DESC LIMIT 8").fetchall():
    print(r)
print("\n== cmmr 20d finalized (forward_days=20) latest 8 ==")
for r in c.execute("SELECT date, ic, samples, win_rate, forward_days FROM cmmr_ic_daily WHERE forward_days=20 ORDER BY date DESC LIMIT 8").fetchall():
    print(r)
print("\n== etf_scores scan_date history ==")
for r in c.execute("SELECT scan_date, COUNT(*), MAX(updated_at) FROM etf_scores GROUP BY scan_date ORDER BY scan_date DESC LIMIT 12").fetchall():
    print(r)
print("\n== etf_scores updated_at max ==", c.execute("SELECT MAX(updated_at) FROM etf_scores").fetchone())
print("\n== other ic tables latest ==")
for t, col in (('center_dual_ic_daily','calc_date'),('fusion_ic_daily','calc_date'),('factor_ic_daily','calc_date'),('mf_observer_ic_daily','calc_date'),('ic_shadow_442','calc_date')):
    try:
        print(t, c.execute(f"SELECT * FROM {t} ORDER BY {col} DESC LIMIT 2").fetchall())
    except Exception as e:
        try:
            print(t, 'fallback', c.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 2").fetchall())
        except Exception as e2:
            print(t, 'err', e, e2)
