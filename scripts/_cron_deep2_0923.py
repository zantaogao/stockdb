import duckdb, sqlite3, os
from collections import defaultdict
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE,'tushare.db'), read_only=True)

# ---- 行业板块（stock_basic.industry 分组日均涨幅）近10日 ----
print("== 行业近10日 日均涨幅（stock_basic.industry 分组）==")
rows = conn.execute("""
SELECT b.industry, d.trade_date, AVG(d.pct_chg) ap, COUNT(*) n
FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date >= '20260910'
GROUP BY 1,2 ORDER BY 1,2""").fetchall()
ind = defaultdict(dict)
for name, dt, ap, n in rows:
    ind[name or '其他'][dt] = ap
dates = sorted({r[1] for r in rows})
print("DATES:", dates)
res = []
for name, dd in ind.items():
    last5 = [dd[x] for x in dates[-5:] if x in dd]
    cum5 = sum(last5) if len(last5)==5 else None
    streak = 0
    for x in reversed(dates):
        v = dd.get(x)
        if v is not None and v > 0: streak += 1
        elif v is not None: break
    res.append((name, cum5, streak, {d: round(dd[d],2) for d in dates[-6:]}))
res.sort(key=lambda r: -(r[1] if r[1] is not None else -99))
for name, cum5, streak, series in res[:20]:
    print(f"{name}\tcum5={None if cum5 is None else round(cum5,2)}\tstreak={streak}\t{series}")
print("...最弱5:")
for name, cum5, streak, series in res[-5:]:
    print(f"{name}\tcum5={None if cum5 is None else round(cum5,2)}\tstreak={streak}\t{series}")

# ---- 关键票日线 ----
codes = ['001225.SZ','688377.SH','603585.SH','300818.SZ','301590.SZ','600076.SH','300854.SZ',
 '300651.SZ','300982.SZ','688335.SH','605598.SH','301575.SZ','002763.SZ','301507.SZ','600645.SH',
 '688659.SH','003027.SZ','300500.SZ','002961.SZ','300120.SZ','300413.SZ','000668.SZ','605580.SH',
 '003001.SZ','000710.SZ','603811.SZ','300658.SZ','688093.SH','688186.SH','301237.SZ','002454.SZ',
 '003017.SZ','300556.SZ','300908.SZ','301050.SZ','002875.SZ','688607.SZ','301370.SZ','688083.SH',
 '603797.SH','300239.SZ','603273.SH','603080.SH','301203.SZ','002961.SZ','600825.SH','600551.SH','688356.SH']
codes = sorted(set(codes))
qs = ",".join(f"'{c}'" for c in codes)
rows = conn.execute(f"""SELECT ts_code, trade_date, close, pct_chg, vol, high, low
    FROM daily WHERE ts_code IN ({qs}) AND trade_date >= '20260811'
    ORDER BY ts_code, trade_date""").fetchall()
per = defaultdict(list)
for ts, dt, cl, pc, vol, hi, lo in rows:
    per[ts].append((dt, cl, pc, vol, hi, lo))
print("\n== 关键票近12日日线（close pct vol_ratio 距20日高 距20日低）==")
for ts in codes:
    arr = per.get(ts, [])
    if not arr:
        print(f"--- {ts}: 无数据"); continue
    closes=[a[1] for a in arr]; vols=[a[3] for a in arr]
    hi20=max(closes[-20:]); lo20=min(closes[-20:])
    v5 = sum(vols[-6:-1])/5 if len(vols)>=6 else None
    line=[]
    for dt,cl,pc,vol,hi,lo in arr[-10:]:
        vr = vol/v5 if v5 else 0
        line.append(f"{dt[4:]}:{cl:+.2f}({pc:+.1f}%,v{vr:.1f})")
    print(f"--- {ts} 距20高={ (closes[-1]/hi20-1)*100:.1f}% 距20低={(closes[-1]/lo20-1)*100:+.1f}% | " + " ".join(line))
conn.close()
