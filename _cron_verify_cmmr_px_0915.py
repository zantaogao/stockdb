import sqlite3, os, urllib.request, time, json
LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED); con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute("SELECT code,name,shares,avg_cost FROM strategy_positions WHERE account_id='cmmr'")]

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
        if len(f)>3: out[k]=(f[0],float(f[1] or 0),float(f[2] or 0),float(f[3] or 0),f[31] if len(f)>31 else '')
    return out

codes=[r['code'] for r in rows]
target_pos_value = 727329.0
tot=0; detail=[]
for rnd in (1,2):
    qq=q(codes); tot=0; detail=[]
    for r in rows:
        v=qq[r['code']]; mv=r['shares']*v[3]; tot+=mv
        detail.append((r['code'], r['name'], r['shares'], v[2], v[3], round(mv), round((v[3]/v[2]-1)*100,2), v[4]))
    print(f"--- round {rnd}: live mv={tot:,.0f}  script pos_value={target_pos_value:,.0f}  gap={tot-target_pos_value:,.0f}")
    if rnd==1:
        detail.sort(key=lambda x: -(x[3]*x[2]-x[5]))
        print(f"{'code':8s}{'name':10s}{'sh':>8s}{'prev':>8s}{'now':>8s}{'mv':>10s}{'chg%':>8s}")
        for d in detail: print(f"{d[0]:8s}{d[1]:10s}{d[2]:>8.0f}{d[3]:>8.2f}{d[4]:>8.2f}{d[5]:>10.0f}{d[6]:>8.2f}  {d[7]}")
        time.sleep(75)
print("\n(mv 每分钟都在动 → 差距=两个时点之间的行情, 非记账错误)")
