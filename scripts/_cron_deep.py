import duckdb, os, json, statistics
from collections import defaultdict
os.chdir('/Users/zantao/.hermes/stockdb')
con = duckdb.connect('tushare.db', read_only=True)
codes = json.load(open('/tmp/codes.json'))
cl = ",".join(f"'{k}'" for k in codes)
rows = con.execute(f"""
 SELECT ts_code, trade_date, open, high, low, close, pct_chg, vol
 FROM daily WHERE ts_code IN ({cl}) AND trade_date>='20260815'
 ORDER BY ts_code, trade_date
""").fetchall()
con.close()
by = defaultdict(list)
for r in rows: by[r[0]].append(r[1:])
for code, hist in sorted(by.items(), key=lambda x: codes[x[0]]['grp']):
    if len(hist) < 25:
        print(f"{code} {codes[code]['n']} [{codes[code]['grp']}] BARS={len(hist)}"); continue
    closes=[h[4] for h in hist]; vols=[h[6] for h in hist]; highs=[h[2] for h in hist]; lows=[h[3] for h in hist]; pcts=[h[5] for h in hist]
    ma20=sum(closes[-20:])/20; ma10=sum(closes[-10:])/10
    sd=statistics.pstdev(closes[-20:])
    bup=ma20+2*sd; blo=ma20-2*sd
    boll=(closes[-1]-blo)/(bup-blo)*100 if bup>blo else 50
    h20=max(highs[-20:]); l20=min(lows[-20:])
    r5=(closes[-1]/closes[-6]-1)*100
    dev20=(closes[-1]/ma20-1)*100
    streak=0
    for p in reversed(pcts):
        if streak>=0 and p>0: streak+=1
        elif streak<=0 and p<0: streak-=1
        else: break
    v20=sum(vols[-21:-1])/20
    spikes=[h[0][4:] for h in hist[-5:] if h[6]>1.8*v20]
    gap='高' if hist[-1][1]>highs[-2] else ('低' if hist[-1][1]<lows[-2] else '')
    last6="|".join(f"{h[0][4:]}:{h[5]:+.1f}/v{h[6]/v20:.1f}" for h in hist[-6:])
    print(f"{codes[code]['grp']}|{code[:6]} {codes[code]['n']}|收{closes[-1]:.2f} 今{pcts[-1]:+.1f}% 5日{r5:+.1f}% MA20偏{dev20:+.1f}%  boll{boll:.0f} 距20日高{(closes[-1]/h20-1)*100:+.1f}% 距20日低{(closes[-1]/l20-1)*100:+.1f}% 连{'涨' if streak>0 else '跌'}{abs(streak)} 放量日{spikes or '-'} 跳空{gap or '-'} || {last6}")
