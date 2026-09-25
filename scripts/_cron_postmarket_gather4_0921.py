# -*- coding: utf-8 -*-
import duckdb, os
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)

codes = {
 # 主账户持仓
 '301093':'华兰股份','688191':'智洋创新','301237':'和顺科技','001332':'锡装股份',
 '300658':'延江股份','600076':'康欣新材','301283':'聚胶股份','002454':'松芝股份',
 '688093':'世华科技','603966':'法兰泰克','601615':'明阳智能','301590':'优优绿能',
 '688186':'广大特材','603202':'天有为','301110':'青木科技','605598':'上海港湾',
 # 三模型融合榜
 '688377':'迪威尔','603585':'苏利股份','603811':'诚意药业','300881':'盛德鑫泰',
 '300970':'华绿生物','300854':'中兰环保','300651':'金陵体育','603190':'亚通精工',
 # 10d独立榜（不在持仓的）
 '001216':'华瓷股份','600825':'新华传媒','603958':'哈森股份','688356':'键凯科技',
 '600103':'青山纸业','603090':'宏盛股份','000711':'京蓝科技','000635':'英力特',
 # 中枢版Top10
 '600527':'江南高纤','603363':'傲农生物','300846':'首都在线','600830':'香溢融通',
 '300324':'旋极信息','300935':'盈建科','002463':'沪电股份','603220':'中贝通信',
 '300501':'海顺新材','001269':'欧晶科技',
 # 中枢+三模型榜新增
 '300876':'蒙泰高新','301163':'宏德股份','300949':'奥雅股份','688681':'科汇股份',
 '603214':'爱婴室','600668':'尖峰集团',
 # CMMR独立榜
 '000017':'深中华A','000430':'张家界','000712':'锦龙股份','000735':'罗牛山',
 '001296':'长江材料','002017':'东信和平','002072':'凯瑞德','002084':'海鸥住工',
 '002104':'恒宝股份','002165':'红宝丽',
 # CMMR+榜
 '002144':'宏达高科','301167':'建研设计','300844':'山水比德','301037':'保立佳',
 '002858':'力盛体育','300621':'维业股份','301006':'迈拓股份',
 # 板块龙头交叉验证
 '000014':'沙河股份','000656':'金科股份','000069':'华侨城A','002244':'滨江集团',
 '000710':'贝瑞基因','300676':'华大基因','002821':'凯莱英','600276':'恒瑞医药',
}

def suff(c):
    return c + ('.SH' if c.startswith(('6','9')) else '.SZ')

out = {}
cl = ','.join(f"'{suff(c)}'" for c in codes)
rows = td.execute(f"""
SELECT ts_code, trade_date, close, pct_chg, vol, high, low FROM daily
WHERE ts_code IN ({cl}) AND trade_date >= '20260720' ORDER BY ts_code, trade_date""").fetchall()
from collections import defaultdict
ser = defaultdict(list)
for r in rows: ser[r[0]].append(r[1:])

for ts, hist in ser.items():
    closes = [float(h[1]) for h in hist]
    chgs = [float(h[2]) for h in hist]
    vols = [float(h[3]) for h in hist]
    highs = [float(h[4]) for h in hist]
    lows = [float(h[5]) for h in hist]
    n = len(closes)
    if n < 21: continue
    c = closes[-1]
    ma20 = sum(closes[-20:])/20
    var = sum((x-ma20)**2 for x in closes[-20:])/20
    sd = var**0.5
    up_band = ma20+2*sd; dn_band = ma20-2*sd
    boll_pos = (c-dn_band)/(up_band-dn_band)*100 if up_band>dn_band else 50
    dev20 = (c/ma20-1)*100
    hi20 = max(highs[-20:]); lo20 = min(lows[-20:])
    hi60 = max(highs[-min(60,n):])
    r5 = (c/closes[-6]-1)*100 if n>=6 else 0
    r10 = (c/closes[-11]-1)*100 if n>=11 else 0
    # 连续涨跌天数
    streak = 0
    for g in chgs[::-1]:
        if streak == 0: streak = 1 if g>0 else (-1 if g<0 else 0)
        elif streak>0 and g>0: streak+=1
        elif streak<0 and g<0: streak-=1
        else: break
    v5avg = sum(vols[-6:-1])/5
    volratio = vols[-1]/v5avg if v5avg>0 else 0
    # 20日内放量日
    bigvol = [hist[i][0][4:] for i in range(max(0,n-20), n) if vols[i] > 2.5*v5avg]
    # 跳空缺口 近10日
    gaps = []
    for i in range(max(1,n-10), n):
        if lows[i] > highs[i-1]: gaps.append(('up', hist[i][0][4:]))
        if highs[i] < lows[i-1]: gaps.append(('dn', hist[i][0][4:]))
    print(f"{codes[ts[:6]]} {ts[:6]} | 收{c:.2f} 5日{r5:+.1f}% 10日{r10:+.1f}% | 偏MA20 {dev20:+.1f}% 布林{boll_pos:.0f}% | 距20日高 {(c/hi20-1)*100:+.1f}% 距60日高 {(c/hi60-1)*100:+.1f}% 距20日低 {(c/lo20-1)*100:+.1f}% | 连{streak} | 今量/5均 {volratio:.1f}x | 近20日放量日{bigvol} | 缺口{gaps}")
