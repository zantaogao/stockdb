import sqlite3, statistics
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for f in ['main_net_1d_pct','main_net_5d_pct','pos_days_11d','elg_net_liq_pct']:
    ics = [r[0] for r in c.execute("SELECT rank_ic FROM mf_observer_ic_daily WHERE factor_name=? AND rank_ic IS NOT NULL", (f,))]
    med = sorted(ics)[len(ics)//2]
    neg = sum(1 for x in ics if x < 0) / len(ics)
    print(f"{f}: mean={statistics.mean(ics):+.4f} med={med:+.4f} 负IC天={neg:.0%} n={len(ics)}")
    years = [r[0] for r in c.execute("SELECT DISTINCT substr(date,1,4) FROM mf_observer_ic_daily WHERE factor_name=?", (f,))]
    for y in sorted(years):
        avg, n = c.execute("SELECT AVG(rank_ic), COUNT(*) FROM mf_observer_ic_daily WHERE factor_name=? AND substr(date,1,4)=?", (f, y)).fetchone()
        print(f"    {y}: mean IC={avg:+.4f} n={n}")