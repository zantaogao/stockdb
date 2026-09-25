#!/usr/bin/env python3
# 0922 补数：榜票近2日涨幅、CMMR vs 三模型榜top10、R7破线、连板/预检
import duckdb, sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)

boards = {
 '三模型': ['603585','300854','300651','300492','688171','300982','301219','301590','301259','688335'],
 'CMMR独立': ['000017','000426','000505','000523','000679','000683','000798','000890','000892','002041'],
 'CMMR+融合': ['603585','300614','301156','002760','002858','300500','300621','003003','002809','605001'],
 '10d独立': ['001216','600743','000668','601811','600825','301237','603958','300413','300120','600551'],
 '中枢版': ['001318','300384','300854','603927','001269','301370','000514','300405','688737','002921'],
 '中枢+三模型': ['300854','300651','300520','688737','002868','002861','300228','300887','000633','300982'],
}
def suf(c): return c+'.SH' if c.startswith(('6','9')) else c+'.SZ'
allc = sorted({suf(c) for l in boards.values() for c in l})
ph = ','.join("'"+c+"'" for c in allc)
rows = tdb.execute(f"SELECT ts_code,trade_date,close,pct_chg,vol FROM daily WHERE ts_code IN ({ph}) AND trade_date>='20260914' ORDER BY ts_code,trade_date").fetchall()
from collections import defaultdict
d = defaultdict(dict)
for tc, dt, cl, pc, v in rows: d[tc][dt] = (cl, pc, v)
print('== 榜票近2日涨幅 (0921chg, 0922chg) ==')
for b, lst in boards.items():
    print('--', b)
    avg21 = avg22 = 0.0; n = 0
    for c in lst:
        s = suf(c); rec = d.get(s, {})
        a = rec.get('20260921', (None,))[1]; z = rec.get('20260922', (None,))[1]
        print(f"  {c} 0921={a} 0922={z}")
        if a is not None: avg21 += a
        if z is not None: avg22 += z
        n += 1
    print(f"  TOP10均值: 0921={avg21/n:+.2f} 0922={avg22/n:+.2f}")

# CMMR独立top10 vs 三模型top10 近3日逐日top10均值对比
print('== 近3日 top10均值对比 CMMR独立 vs 三模型 ==')
for dt in ['20260918','20260921','20260922']:
    a = sum(d[suf(c)].get(dt,(0,0))[1] or 0 for c in boards['CMMR独立'])/10
    z = sum(d[suf(c)].get(dt,(0,0))[1] or 0 for c in boards['三模型'])/10
    m = sum(d[suf(c)].get(dt,(0,0))[1] or 0 for c in boards['10d独立'])/10
    print(f"  {dt}: CMMR={a:+.2f} 三模型={z:+.2f} 10d={m:+.2f}")

# R7 破线: strategy_positions hold, 现价<=成本*0.94（收盘价）
print('== R7 浮亏破线名单（收盘价口径, cost*0.94） ==')
pos = led.execute("SELECT account_id,code,name,avg_cost FROM strategy_positions WHERE status='hold'").fetchall()
for acc, c, nm, cost in pos:
    rec = d.get(suf(c), {})
    cl = rec.get('20260922', (None,))[0]
    if cl and cost and cl <= cost*0.94:
        print(f"  {acc} {nm} {c} cost={cost} close={cl} ({(cl/cost-1)*100:+.1f}%)")

# 主账户昨日判断对账用：哈森股份20日高、中岩大地等
print('== 对账辅助 ==')
for c in ['603958','003001','605598']:
    s = suf(c)
    hs = max((v[0] for dt, v in d.get(s, {}).items()), default=None)
    print(c, '近6日高=', hs, '0922收=', d.get(s, {}).get('20260922', (None,))[0])
