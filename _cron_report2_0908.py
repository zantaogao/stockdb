import duckdb, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
codes = {
 '三模型融合': [('603966.SH','法兰泰克'),('301093.SZ','华兰股份'),('688377.SH','迪威尔'),('001332.SZ','锡装股份'),('688399.SH','硕世生物'),('300818.SZ','耐普矿机'),('300952.SZ','恒辉安防'),('301237.SZ','和顺科技'),('300680.SZ','隆盛科技'),('002487.SZ','大金重工')],
 'CMMR独立': [('603089.SH','正裕工业'),('300906.SZ','日月明'),('688133.SH','泰坦科技'),('001230.SZ','劲旅环境'),('603095.SH','越剑智能'),('300615.SZ','欣天科技'),('300358.SZ','楚天科技'),('603519.SH','立霸股份'),('603816.SH','顾家家居'),('688356.SH','键凯科技')],
 'CMMR+': [('688217.SH','睿昂基因'),('603801.SH','志邦家居'),('688793.SH','倍轻松'),('300886.SZ','华业香料'),('301552.SZ','科力装备'),('603900.SH','莱绅通灵'),('001277.SZ','速达股份'),('688606.SH','奥泰生物'),('301130.SZ','西点药业'),('688317.SH','之江生物')],
 '中枢版': [('300543.SZ','朗科智能'),('301528.SZ','多浦乐'),('300578.SZ','会畅科技'),('300783.SZ','三只松鼠'),('300455.SZ','航天智装'),('603089.SH','正裕工业'),('600048.SH','保利发展'),('301500.SZ','飞南资源'),('002674.SZ','兴业科技'),('300528.SZ','幸福蓝海')],
 '中枢版+三模型': [('300724.SZ','捷佳伟创'),('300543.SZ','朗科智能'),('301053.SZ','远信工业'),('300176.SZ','鸿特科技'),('688335.SH','复洁科技'),('688776.SH','国光电气'),('601778.SH','晶科科技'),('002674.SZ','兴业科技'),('301518.SZ','长华化学'),('002887.SZ','绿茵生态')],
}
allc = sorted({c for v in codes.values() for c,_ in v})
td = duckdb.connect('tushare.db', read_only=True)
ph = ','.join(['?']*len(allc))
rows = td.execute(f"""SELECT ts_code, trade_date, close, high, low FROM daily
  WHERE ts_code IN ({ph}) AND trade_date >= '20260601' ORDER BY ts_code, trade_date""", allc).fetchall()
from collections import defaultdict
by = defaultdict(list)
for c,d,cl,h,l in rows: by[c].append((d,cl,h,l))
out = {}
for c in allc:
    s = by[c]
    if len(s) < 25: out[c] = 'INSUFFICIENT'; continue
    closes = [x[1] for x in s]
    last = closes[-1]
    ma20 = sum(closes[-20:])/20
    ma5 = sum(closes[-5:])/5
    dev = (last/ma20-1)*100
    r5 = (closes[-1]/closes[-6]-1)*100
    # bollinger 20,2 position
    var = sum((x-ma20)**2 for x in closes[-20:])/20
    sd = var**0.5
    ub, lb = ma20+2*sd, ma20-2*sd
    bollpos = (last-lb)/(ub-lb)*100 if ub>lb else 50
    newhigh20 = last >= max(x[2] for x in s[-20:]) - 1e-9
    out[c] = dict(close=round(last,2), dev20=round(dev,1), r5=round(r5,1), boll=round(bollpos,0), nh20=newhigh20)
for grp,v in codes.items():
    print('###', grp)
    for c,name in v:
        print(name, c, out.get(c))