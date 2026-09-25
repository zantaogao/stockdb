#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第三轮：Top10票日线 + 持仓票日线 + 管理区IC行"""
import duckdb, sqlite3, json, os
BASE = os.path.expanduser('~/.hermes/stockdb')
out = {}
tdb = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

codes = {
 # 主账户持仓18
 '603202.SH':'天有为','002454.SZ':'松芝股份','605598.SH':'上海港湾','688093.SH':'世华科技',
 '300658.SZ':'延江股份','688186.SH':'广大特材','301110.SZ':'青木科技','301093.SZ':'华兰股份',
 '001332.SZ':'锡装股份','603966.SH':'法兰泰克','301237.SZ':'和顺科技','601615.SH':'明阳智能',
 '301283.SZ':'聚胶股份','600076.SH':'康欣新材','301590.SZ':'优优绿能','603811.SH':'诚意药业',
 '301575.SZ':'艾芬达','300651.SZ':'金陵体育',
 # 三模型融合榜
 '603585.SH':'苏利股份','001225.SZ':'和泰机电','300492.SZ':'华图山鼎','688117.SH':'圣诺生物',
 '688377.SH':'迪威尔','300970.SZ':'华绿生物','300854.SZ':'中兰环保','603090.SH':'宏盛股份',
 # CMMR独立榜
 '000017.SZ':'深中华A','000019.SZ':'深粮控股','000428.SZ':'华天酒店','000430.SZ':'张家界',
 '000505.SZ':'京粮控股','000523.SZ':'红棉股份','000524.SZ':'岭南控股','000533.SZ':'顺钠股份',
 '000553.SZ':'安道麦A','000554.SZ':'泰山石油',
 # CMMR+三模型榜
 '600262.SH':'北方股份','301156.SZ':'美农生物','300614.SZ':'百川畅银','605077.SH':'华康股份',
 '002535.SZ':'林州重机','002809.SZ':'红墙股份','002661.SZ':'克明食品',
 # 10d独立榜
 '603823.SH':'百合花','600499.SH':'科达制造','300413.SZ':'芒果超媒','000668.SZ':'荣丰控股',
 '603999.SH':'读者传媒','002961.SZ':'瑞达期货','003040.SZ':'楚天龙',
 # 中枢版榜
 '000952.SZ':'广济药业','600048.SH':'保利发展','002133.SZ':'广宇集团','300564.SZ':'筑博设计',
 '688500.SH':'慧辰股份','603079.SH':'圣达生物','600875.SH':'东方电气','300136.SZ':'信维通信',
 '002881.SZ':'美格智能',
 # 中枢+三模型榜
 '300055.SZ':'万邦达','300533.SZ':'冰川网络','603737.SH':'三棵树','600785.SH':'新华百货',
 '301232.SZ':'飞沃科技','600791.SH':'京能置业','300228.SZ':'富瑞特装','300898.SZ':'熊猫乳品',
}
cl = ",".join(f"'{c}'" for c in codes)
rows = tdb.execute(f"""
  SELECT ts_code, trade_date, close, pct_chg, vol, amount
  FROM daily WHERE ts_code IN ({cl}) AND trade_date >= '20260820'
  ORDER BY ts_code, trade_date
""").fetchall()
daily = {}
for r in rows: daily.setdefault(r[0], []).append((r[1], r[2], r[3], r[4]))

def feats(series):
    if not series: return None
    closes=[s[1] for s in series]; dates=[s[0] for s in series]
    last=closes[-1]
    hi20=max(closes[-20:]); lo20=min(closes[-20:])
    hi_all=max(closes); lo_all=min(closes)
    ma20=sum(closes[-20:])/20
    # 连续涨跌天数
    streak=0
    for p in reversed([s[2] for s in series]):
        if streak>=0 and p>0 and (streak==0 or streak>0): streak+=1
        elif streak<=0 and p<0 and (streak==0 or streak<0): streak-=1
        else: break
    cum5=sum(s[2] for s in series[-5:])
    # 最近5日放量日（vol vs 20日均量）
    vols=[s[3] for s in series]
    v20=sum(vols[-20:])/20 if len(vols)>=20 else None
    bigvol=[dates[i] for i in range(max(0,len(vols)-5),len(vols)) if v20 and vols[i]>1.8*v20]
    return dict(n=len(series), last=last, chg=series[-1][2],
                dist_hi20=round((last/hi20-1)*100,1), dist_lo20=round((last/lo20-1)*100,1),
                dist_hi_all=round((last/hi_all-1)*100,1),
                ma20_dev=round((last/ma20-1)*100,1), cum5=round(cum5,1),
                streak=streak, bigvol_days=bigvol,
                last5=[(d[0][4:], d[2]) for d in series[-5:]])
out['stocks'] = {f"{codes[c]} {c}": feats(daily.get(c)) for c in codes}

# 管理区 IC 行（fusion_ic / center_dual 0924）
sc = sqlite3.connect(os.path.join(BASE,'signals.db'))
out['fusion_ic_new'] = sc.execute("SELECT date, ROUND(ic,4), samples FROM fusion_ic_daily WHERE date>='2026-09-23' ORDER BY date").fetchall()
out['dual_ic_new'] = sc.execute("SELECT date, ROUND(ic,4), top_ret, bottom_ret FROM center_dual_ic_daily WHERE date>='20260923' ORDER BY date").fetchall()
out['cmmr_ic'] = sc.execute("SELECT * FROM cmmr_ic_daily ORDER BY 1 DESC LIMIT 5").fetchall()
out['cmmr_top10_ic'] = sc.execute("SELECT * FROM cmmr_top10_ic_daily ORDER BY 1 DESC LIMIT 5").fetchall()
sc.close()
tdb.close()
print(json.dumps(out, ensure_ascii=False, default=str))
