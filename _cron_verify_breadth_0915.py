import urllib.request, time, random, duckdb, statistics, os

def q(codes):
    out={}
    lst=[('sh' if (c[0]=='6' or c.startswith('68') or c[0]=='9') else 'sz')+c for c in codes]
    url="https://hq.sinajs.cn/list="+",".join(lst)
    req=urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    txt=urllib.request.urlopen(req,timeout=10).read().decode('gbk','ignore')
    for line in txt.strip().split('\n'):
        if '="' not in line: continue
        k=line.split('=')[0].split('_')[-1][2:]
        f=line.split('="')[1].rstrip('";').split(',')
        if len(f)>3 and float(f[2] or 0)>0 and float(f[3] or 0)>0:
            out[k]=(float(f[2]),float(f[3]))
    return out

# 指数
idx = q(['000852','000001','399006','399303','000300','932000'])
print("=== 指数实时 ===")
for k,v in idx.items():
    print(f"{k}: {v[1]:.2f}  {(v[1]/v[0]-1)*100:+.2f}%")

# 全市场样本（从 tushare.db 取最新交易日活跃票）
dd = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
maxd = dd.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
codes = [r[0].split('.')[0] for r in dd.execute(
    f"SELECT ts_code FROM daily WHERE trade_date='{maxd}' AND (ts_code LIKE '00%' OR ts_code LIKE '30%' OR ts_code LIKE '60%')").fetchall()]
random.seed(7); samp = random.sample(codes, 600)
chg=[]
for i in range(0,len(samp),60):
    d=q(samp[i:i+60])
    for k,v in d.items(): chg.append((v[1]/v[0]-1)*100)
    time.sleep(0.2)
chg.sort()
print(f"\n=== 全市场抽样 n={len(chg)} (源: sina 实时, 交易日 {maxd}) ===")
print(f"中位涨跌 {statistics.median(chg):+.2f}%  均值 {statistics.mean(chg):+.2f}%")
print(f"下跌家数占比 {sum(1 for x in chg if x<0)/len(chg)*100:.0f}%")
for p in (5,25,50,75,95):
    print(f"  P{p}: {chg[int(len(chg)*p/100)-1]:+.2f}%")
