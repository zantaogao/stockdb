#!/usr/bin/env python3
"""深复盘 #2：六榜60票日线 + 板块（stock_info行业加权）+ 榜单交叉 + 信号复算"""
import duckdb, sqlite3
from collections import defaultdict

TD = '/Users/zantao/.hermes/stockdb'
d = duckdb.connect(f'{TD}/tushare.db', read_only=True)

boards = {
 '三模型融合': ['600499.SH','002545.SZ','603226.SH','600547.SH','002961.SZ','688629.SH','600363.SH','688117.SH','002625.SZ','001225.SZ'],
 'CMMR独立': ['000428.SZ','000430.SZ','000533.SZ','000550.SZ','000558.SZ','000668.SZ','000713.SZ','000720.SZ','000721.SZ','000722.SZ'],
 'CMMR+三模型': ['600547.SH','001225.SZ','688217.SH','688011.SH','688031.SH','688329.SH','688466.SH','300614.SZ','300621.SZ','688695.SH'],
 '10d独立': ['600547.SH','603226.SH','001330.SZ','688629.SH','002625.SZ','600499.SH','002961.SZ','688117.SH','688668.SH','600869.SH'],
 '中枢版Top10': ['300822.SZ','301070.SZ','603099.SH','300255.SZ','688663.SH','603201.SH','603202.SH','002595.SZ','301307.SZ','000759.SZ'],
 '中枢+三模型': ['300640.SZ','688096.SH','002554.SZ','301512.SZ','688348.SH','688051.SH','300971.SZ','688671.SH','300837.SZ','688391.SH'],
}
allc = sorted({c for v in boards.values() for c in v})
q = ",".join(f"'{c}'" for c in allc)
rows = d.execute(f"""
  WITH x AS (SELECT ts_code, trade_date, open, high, low, close, pct_chg, vol,
      AVG(close) OVER w ma20, STDDEV(close) OVER w sd20,
      AVG(vol) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) vma6
    FROM daily WHERE ts_code IN ({q}) AND trade_date>='20260815'
    WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)),
  last AS (SELECT * FROM x WHERE trade_date='20260928'),
  ext AS (SELECT ts_code, MAX(high) h20, MIN(low) l20 FROM x WHERE trade_date>='20260825' GROUP BY ts_code)
  SELECT l.ts_code, s.name, s.industry,
     ROUND((l.close/l.ma20-1)*100,1),
     ROUND((l.close-(l.ma20-2*l.sd20))/NULLIF(4*l.sd20,0)*100,0),
     ROUND((l.close/e.h20-1)*100,1),
     ROUND(l.close/e.l20*100-100,1),
     l.vol/NULLIF(l.vma6,0),
     (SELECT ROUND((EXP(SUM(LN(1+pct_chg/100.0)))-1)*100,1) FROM x x2 WHERE x2.ts_code=l.ts_code AND x2.trade_date>'20260921'),
     (SELECT MAX(pct_chg) FROM x x3 WHERE x3.ts_code=l.ts_code AND x3.trade_date>'20260915')
  FROM last l JOIN ext e ON l.ts_code=e.ts_code
  LEFT JOIN stock_basic s ON s.ts_code=l.ts_code
""").fetchall()
info = {}
for r in rows:
    info[r[0]] = r
print('票|devMA20%|布林位%|距20日高%|距20日低%|量比|5日涨%|近9日最大单日%')
for c in allc:
    r = info.get(c)
    if r: print(c, r[2], '| dev20', r[3], '| boll', r[4], '| hq', r[5], '| lq', r[6], '| volx', round(r[7] or 0,1), '| 5d', r[8], '| max1', r[9])
    else: print(c, 'MISSING')

print('==== 每票近6日 pct_chg ====')
for c in allc:
    seq = d.execute("SELECT trade_date, pct_chg, vol FROM daily WHERE ts_code=? AND trade_date>='20260918' ORDER BY trade_date", [c]).fetchall()
    # consecutive up days ending today
    ups = 0
    for s in reversed(seq):
        if (s[1] or 0) > 0: ups += 1
        else: break
    print(c, [(s[0][-4:], round(s[1] or 0,1)) for s in seq], 'up streak', ups)

print('==== 板块（stock_info行业等权，近5交易日） ====')
dates = [r[0] for r in d.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 6").fetchall()][::-1]
ind = {r[0]: r[1] for r in d.execute("SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL").fetchall()}
for dt in dates[1:]:
    agg = defaultdict(list)
    for ts, pc in d.execute("SELECT ts_code, pct_chg FROM daily WHERE trade_date=? AND pct_chg IS NOT NULL", [dt]).fetchall():
        i = ind.get(ts)
        if i: agg[i].append(pc)
    day = sorted(((i, sum(v)/len(v)) for i,v in agg.items() if len(v)>=8), key=lambda x:-x[1])
    print(dt, 'TOP:', [(i, round(p,1)) for i,p in day[:6]], 'BOT:', [(i, round(p,1)) for i,p in day[-6:]])
# 5日累计
cum = defaultdict(lambda: defaultdict(list))
for dt in dates:
    for ts, pc in d.execute("SELECT ts_code, pct_chg FROM daily WHERE trade_date>=? AND pct_chg IS NOT NULL", [dates[0]]).fetchall():
        i = ind.get(ts)
        if i: cum[i][dt]=pc
print('---- 5日累计(行业等权,近5交易日) top/bot ----')
cums = sorted(((i, sum(dd.values())) for i,dd in cum.items() if len(dd)>=5), key=lambda x:-x[1])
print('TOP:', [(i, round(p,1)) for i,p in cums[:10]])
print('BOT:', [(i, round(p,1)) for i,p in cums[-10:]])
# 连续强势天数（等权日涨幅>0 连续）
strong = {}
for i,dd in cum.items():
    if len(dd)<5: continue
    s=0
    for dt in dates[::-1]:
        if dd.get(dt,0)>0: s+=1
        else: break
    strong[i]=s
print('连续强势天数(>=2):', sorted([(i,s) for i,s in strong.items() if s>=2], key=lambda x:-x[1]))

d.close()
s = sqlite3.connect(f'{TD}/signals.db')
print('==== 榜单交叉 ====')
cnt = defaultdict(list)
for b, lst in boards.items():
    for c in lst: cnt[c].append(b)
cross = {c:v for c,v in cnt.items() if len(v)>=2}
print('共振票:', cross)
print('重合统计:')
import itertools
for a,bb in itertools.combinations(boards,2):
    ov = set(boards[a])&set(boards[bb])
    if ov: print(a,'∩',bb,ov)
print('==== 中枢 0928 名单复算（fusion_center_signals） ====')
cols=[r[1] for r in s.execute("PRAGMA table_info(fusion_center_signals)").fetchall()]
print('cols:',cols)
for r in s.execute("SELECT * FROM fusion_center_signals WHERE date IN ('20260928','2026-09-28') ORDER BY center_score ASC LIMIT 12").fetchall():
    print(r)
