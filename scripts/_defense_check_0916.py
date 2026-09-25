import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
con.execute("ATTACH '/Users/zantao/.hermes/stockdb/signals.db' AS sig")
rows = con.execute("""
select code, name, shares, latest_price, avg_cost, pnl_pct, buy_date
from holdings where status='hold' order by shares*latest_price desc
""").fetchall()
tot = 0
for r in rows:
    mv = (r[3] or 0) * (r[2] or 0)
    tot += mv
    pnl = r[5] if r[5] is not None else 0
    print(f"{r[0]:<9}{(r[1] or ''):<8}买{r[6]}  {mv/1e4:>6.1f}万  {pnl:>7.2f}%")
print(f"合计 {tot/1e4:.1f} 万")
latest = con.execute("select max(date) from sig.signal_history").fetchone()[0]
print("最新信号日:", latest)
fh = dict(con.execute("select stock_code, round(fusion_score,1) from sig.signal_history where date=?", (latest,)).fetchall())
for r in rows:
    suf = r[0] + ('.SZ' if r[0].startswith(('0', '3')) else '.SH')
    print(r[0], r[1], 'fusion=', fh.get(r[0]) or fh.get(suf))
