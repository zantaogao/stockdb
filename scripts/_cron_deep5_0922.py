#!/usr/bin/env python3
# 深复盘：每票形态自算（距前高/前低、连涨跌、放量日、跳空、MA20偏离、布林位置、5日涨幅）
import duckdb, os, json
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)

stocks = {
 'main_hold': ['301093','688191','301237','300658','688093','301283','001332','002454','600076','603966','301575','603202','301590','688186','601615','603811','301110','605598'],
 'fusion3m_top10': ['603585','300854','300651','300492','688171','300982','301219','301590','301259','688335'],
 'center_top10': ['001318','300384','300854','603927','001269','301370','000514','300405','688737','002921'],
 'dual_top10': ['300854','300651','300520','688737','002868','002861','300228','300887','000633','300982'],
 'reg10_top10': ['001216','600743','000668','601811','600825','301237','603958','300413','300120','600551'],
 'cmmr_top10': ['000017','000426','000505','000523','000679','000683','000798','000890','000892','002041'],
 'cmmrf_top10': ['603585','300614','301156','002760','002858','300500','300621','003003','002809','605001'],
}
codes = sorted(set(sum(stocks.values(), [])))
ph = ",".join("'%s.SZ'" % c if not c.startswith(('6','9')) else "'%s.SH'" % c for c in codes)
rows = tdb.execute(f"""SELECT ts_code, trade_date, open, high, low, close, pct_chg, vol FROM daily
 WHERE ts_code IN ({ph}) AND trade_date >= '20260720' ORDER BY ts_code, trade_date""").fetchall()

from collections import defaultdict
by = defaultdict(list)
for r in rows: by[r[0]].append(r)

out = {}
for ts, bars in by.items():
    closes = [b[5] for b in bars]; vols=[b[7] for b in bars]; dates=[b[1] for b in bars]
    if len(bars) < 25: out[ts] = 'insufficient'; continue
    c = closes[-1]
    ma20 = sum(closes[-20:])/20
    dev20 = (c/ma20-1)*100
    # bollinger 20,2
    import statistics
    sd = statistics.pstdev(closes[-20:])
    ub, lb = ma20+2*sd, ma20-2*sd
    bpos = (c-lb)/(ub-lb)*100 if ub>lb else 50
    chg5 = (c/closes[-6]-1)*100 if len(closes)>=6 else None
    hi20 = max(closes[-20:]); dist_hi20 = (c/hi20-1)*100
    hi120 = max(closes); dist_hi_all = (c/hi120-1)*100
    lo20 = min(closes[-20:]); dist_lo20=(c/lo20-1)*100
    # streak
    streak=0
    for p in reversed([b[6] for b in bars]):
        if streak>=0 and p>0: streak+=1
        elif streak<=0 and p<0: streak-=1
        else: break
    # volume spike last5 (vs 20avg)
    v20 = sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols[:-1])/max(1,len(vols)-1)
    spikes = [(dates[i], round(vols[i]/v20,1), round(bars[i][6],1)) for i in range(len(bars)-5,len(bars)) if v20>0 and vols[i]>2*v20]
    # gap up/down last 5
    gaps = [(dates[i], round((bars[i][2]/bars[i-1][5]-1)*100,1)) for i in range(len(bars)-5,len(bars)) if abs(bars[i][2]/bars[i-1][5]-1)>0.03]
    out[ts] = dict(close=round(c,2), dev20=round(dev20,1), boll=round(bpos,0), chg5=round(chg5,1),
                   d_hi20=round(dist_hi20,1), d_hi120=round(dist_hi_all,1), d_lo20=round(dist_lo20,1),
                   streak=streak, last5=[round(b[6],1) for b in bars[-5:]], spikes=spikes, gaps=gaps)

def suf(c): return c+'.SH' if c.startswith(('6','9')) else c+'.SZ'
for grp, lst in stocks.items():
    print('####', grp)
    for c in lst:
        print(c, json.dumps(out.get(suf(c),'missing'), ensure_ascii=False))
