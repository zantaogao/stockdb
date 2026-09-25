import duckdb, os
os.chdir('/Users/zantao/.hermes/stockdb')
dd = duckdb.connect('tushare.db', read_only=True)

lists = {
 '三模型融合': ['001332.SZ','600363.SH','301479.SZ','300622.SZ' if 0 else '300622.SZ','300680.SZ','688081.SH','002487.SZ','300812.SZ','301590.SZ','601615.SH'],
 'CMMR独立': ['301257.SZ','603801.SH','301130.SZ','001277.SZ','301166.SZ','300937.SZ','688793.SH','603102.SH','300381.SZ','301509.SZ'],
 'CMMR+': ['002820.SZ','688217.SH','301130.SZ','603089.SH','301166.SZ','600833.SH','300886.SZ','300937.SZ','605189.SH','301336.SZ'],
 '中枢版': ['002187.SZ','002320.SZ','688698.SH','301055.SZ','002469.SZ','300349.SZ','301599.SZ','600732.SH','688061.SH','688372.SH'],
 '中枢版+三模型': ['300812.SZ','688698.SH','301042.SZ','688776.SH','301232.SZ','688148.SH','688486.SH','002402.SZ','300986.SZ','300724.SZ'],
}
lists['三模型融合'][3]='300622.SZ'  # 阳光电源 is 300274.SZ
lists['三模型融合'] = ['001332.SZ','600363.SH','301479.SZ','300274.SZ','300680.SZ','688081.SH','002487.SZ','300812.SZ','301590.SZ','601615.SH']

allc = sorted({c for v in lists.values() for c in v})
q = ",".join("'%s'" % c for c in allc)
rows = dd.execute(f"""
SELECT ts_code, trade_date, close FROM daily
WHERE ts_code IN ({q}) AND trade_date >= '20260701'
ORDER BY ts_code, trade_date""").fetchall()
from collections import defaultdict
ser = defaultdict(list)
for c,d,p in rows: ser[c].append((d,p))

for name, codes in lists.items():
    print("=====", name)
    for c in codes:
        s = [p for d,p in ser[c]]
        if len(s) < 25:
            print(c, "insufficient"); continue
        last = s[-1]
        ma20 = sum(s[-20:])/20
        # bollinger 20,2
        import statistics
        sd = statistics.pstdev(s[-20:])
        up, lo = ma20+2*sd, ma20-2*sd
        bollpos = (last-lo)/(up-lo)*100 if up>lo else 50
        chg5 = (s[-1]/s[-6]-1)*100
        is20high = last >= max(s[-20:])*0.999
        dev = (last/ma20-1)*100
        print(f"{c} close={last:.2f} devMA20={dev:+.1f}% boll={bollpos:.0f}% chg5={chg5:+.1f}% 20dhigh={is20high}")