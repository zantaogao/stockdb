#!/usr/bin/env python3
# 盘前步骤2.5 持仓/榜内票日线核验 2026-09-30
import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = ['600076.SH','301575.SZ','301093.SZ','601615.SH','688093.SH','688217.SH',
         '600547.SH','603900.SH','300724.SZ','603823.SH','002961.SZ','001225.SZ',
         '300839.SZ','600936.SH','002595.SZ','300651.SZ','002454.SZ','301237.SZ',
         '688117.SH','600363.SH','300543.SZ']
q = """
SELECT ts_code, trade_date, open, high, low, close, vol FROM daily
WHERE ts_code IN (%s) AND trade_date >= '20260825'
ORDER BY ts_code, trade_date
""" % ",".join("'%s'" % c for c in codes)
rows = con.execute(q).fetchall()
import collections
by = collections.defaultdict(list)
for r in rows: by[r[0]].append(r)
names = {'600076.SH':'康欣新材','301575.SZ':'艾芬达','301093.SZ':'华兰股份','601615.SH':'明阳智能','688093.SH':'世华科技','688217.SH':'睿昂基因','600547.SH':'山东黄金','603900.SH':'莱绅通灵','300724.SZ':'捷佳伟创','603823.SH':'百合花','002961.SZ':'瑞达期货','001225.SZ':'和泰机电','300839.SZ':'博汇股份','600936.SH':'北投科技','002595.SZ':'豪迈科技','300651.SZ':'金陵体育','002454.SZ':'松芝股份','301237.SZ':'和顺科技','688117.SH':'华丰科技','600363.SH':'联创光电','300543.SZ':'朗科智能'}
for c in codes:
    rs = by.get(c, [])
    if not rs:
        print(f"{names[c]} {c}: 无日线"); continue
    closes = [r[5] for r in rs]; dates=[r[1] for r in rs]; vols=[r[6] for r in rs]
    last = closes[-1]; d = dates[-1]
    c5 = (last/closes[-6]-1)*100 if len(closes)>=6 else None
    hi20 = max(closes[-20:]); dist_hi = (last/hi20-1)*100
    lo20 = min(closes[-20:])
    # consecutive up days ending last
    up=0; dn=0
    for i in range(len(closes)-1,0,-1):
        ch=closes[i]/closes[i-1]-1
        if up==0 or True:
            if ch>0 and up==len(closes)-1-i or dn==len(closes)-1-i: pass
    upc=0; dnc=0
    for i in range(len(closes)-1,0,-1):
        ch=closes[i]/closes[i-1]-1
        if ch>0 and upc== (0 if upc==0 else upc) : pass
    # simpler
    upc=0
    for i in range(len(closes)-1,0,-1):
        if closes[i]>closes[i-1]: upc+=1
        else: break
    dnc=0
    for i in range(len(closes)-1,0,-1):
        if closes[i]<closes[i-1]: dnc+=1
        else: break
    c3=(last/closes[-4]-1)*100 if len(closes)>=4 else None
    v20=sum(vols[-21:-1])/20 if len(vols)>=21 else None
    vr = vols[-1]/v20 if v20 else None
    # last 5 pct changes
    pcts=[(closes[i]/closes[i-1]-1)*100 for i in range(len(closes)-5,len(closes))]
    print(f"{names[c]} {c} last {d} close {last:.2f} | 5日{c5:+.1f}% 3日{c3:+.1f}% | 距20日高{dist_hi:+.1f}%(高{hi20:.2f}) 20日低{lo20:.2f} | 连涨{upc}/连跌{dnc} | 量比{vr:.2f} | 近5日% {['%+.1f'%p for p in pcts]}")
