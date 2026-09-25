#!/usr/bin/env python3
# 榜单票日线口径计算 20260917
import duckdb, os, json
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
TU = duckdb.connect('tushare.db', read_only=True)

boards = {
'三模型融合': ['605056.SH','603585.SH','300970.SZ','688191.SH','001332.SZ','301575.SZ','300652.SZ','603811.SH','301233.SZ','300952.SZ'],
'中枢版': ['688565.SH','300432.SZ','605178.SH','688592.SH','002829.SZ','603970.SH','300686.SZ','300838.SZ','603093.SH','603180.SH'],
'中枢+三模型': ['688592.SH','301538.SZ','001238.SZ','603093.SH','301503.SZ','688399.SH','002943.SZ','301276.SZ','300501.SZ','688288.SH'],
'10d独立': ['301390.SZ','000930.SZ','600103.SH','603999.SH','002349.SZ','601949.SH','603230.SH','603823.SH','603226.SH','688300.SH'],
'CMMR独立': ['300970.SZ','300935.SZ','600785.SH','301158.SZ','603958.SH','300774.SZ','603036.SH','603721.SH','600712.SH','600892.SH'],
'CMMR+三模型': ['688217.SH','688638.SH','300844.SZ','688793.SH','300500.SZ','301181.SZ','301119.SZ','301519.SZ','603073.SH','688681.SH'],
'agent持仓': ['603409.SH','300837.SZ','001238.SZ','605598.SH','300881.SZ','301053.SZ','688607.SH','301338.SZ'],
'cmmr持仓': ['000802.SZ','002742.SZ','002686.SZ','002244.SZ','000710.SZ','603089.SH','603758.SZ','603079.SZ','603036.SH','605286.SH','600066.SH','300935.SZ','688265.SH','300779.SZ'],
'cmmr+持仓': ['003001.SZ','688793.SH','603382.SH','688004.SH','688217.SH','301130.SZ','001277.SZ'],
'center_dual持仓': ['601778.SH','300543.SZ','300982.SZ','688355.SH','002402.SZ','300812.SZ','002674.SZ','688191.SH','002595.SZ','688063.SH','688776.SH','688155.SH','300724.SZ','688275.SZ'],
'center_top10持仓': ['000897.SZ','600512.SH','000421.SZ','600731.SH','600100.SH','601319.SH','300349.SZ','002199.SZ','601886.SH','603955.SZ','003017.SZ','300321.SZ','300474.SZ','688099.SH','600563.SH'],
'reg10持仓': ['600076.SH','600785.SH','300328.SZ','300839.SZ','002491.SZ','001268.SZ','300864.SZ','003018.SZ','688503.SH'],
}
seen={}
allc=sorted({c for v in boards.values() for c in v})
print('total uniq:',len(allc))
data={}
for c in allc:
    rows=TU.execute("""SELECT trade_date,close,pct_chg,vol,high,low FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60""",[c]).fetchall()
    if not rows: data[c]=None; continue
    rows=list(reversed(rows))
    closes=[r[1] for r in rows]
    ma20=sum(closes[-20:])/20
    var=sum((x-ma20)**2 for x in closes[-20:])/20; sd=var**0.5
    up=ma20+2*sd; dn=ma20-2*sd
    last=closes[-1]
    boll=(last-dn)/(up-dn)*100 if up>dn else 50
    hi20=max(r[4] for r in rows[-20:-1])
    chg5=(closes[-1]/closes[-6]-1)*100 if len(closes)>=6 else None
    # 连续涨starting day: find last down day
    updays=0
    for r in reversed(rows):
        if r[2]>0.02: updays+=1
        else: break
    vol5avg=sum(r[3] for r in rows[-6:-1])/5
    data[c]=dict(d1=round(rows[-1][2],2), ma20dev=round((last/ma20-1)*100,1),
        boll=round(boll,0), d20hi=round((last/hi20-1)*100,1),
        chg5=round(chg5,1) if chg5 is not None else None,
        updays=updays, volratio=round(rows[-1][3]/vol5avg,2) if vol5avg else None,
        close=last)
for b,codes in boards.items():
    print('\n##',b)
    for c in codes:
        d=data.get(c)
        print(c, d if d else 'NOROW')
print('\nDONE')
