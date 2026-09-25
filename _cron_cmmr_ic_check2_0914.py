import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('signals.db')
print("== cmmr_ic_daily cols ==")
cols = [r[1] for r in c.execute("PRAGMA table_info(cmmr_ic_daily)").fetchall()]
print(cols)
print("\n== cmmr_ic_daily latest 10 ==")
for r in c.execute("SELECT * FROM cmmr_ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall():
    print(r)
print("\n== cmmr_ic_daily recent calc_date counts ==")
for r in c.execute("SELECT calc_date, COUNT(*), MAX(signal_date) FROM cmmr_ic_daily GROUP BY calc_date ORDER BY calc_date DESC LIMIT 8").fetchall():
    print(r)
print("\n== etf_scores scan_date history ==")
for r in c.execute("SELECT scan_date, COUNT(*), MAX(updated_at) FROM etf_scores GROUP BY scan_date ORDER BY scan_date DESC LIMIT 12").fetchall():
    print(r)
print("\n== factor_ic_roll / center_dual_ic_daily / fusion_ic_daily latest ==")
for t in ('center_dual_ic_daily','fusion_ic_daily','factor_ic_daily','mf_observer_ic_daily'):
    try:
        rows = c.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 3").fetchall()
        print(t, rows)
    except Exception as e:
        print(t, 'err', e)
