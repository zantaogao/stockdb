#!/usr/bin/env python3
# 盘前2.5核验：持仓+榜内票 最近日线，自算5日涨幅/距20日高/近3日累计
import duckdb, sqlite3, json

WATCH = {
 # 主账户持仓
 '301093.SZ':'华兰股份','301237.SZ':'和顺科技','688093.SH':'世华科技','301283.SZ':'聚胶股份',
 '300658.SZ':'延江股份','603966.SH':'法兰泰克','002454.SZ':'松芝股份','688186.SH':'广大特材',
 '001332.SZ':'锡装股份','603202.SH':'天有为','601615.SH':'明阳智能','301590.SZ':'优优绿能',
 '603811.SH':'诚意药业','300651.SZ':'金陵体育','301110.SZ':'青木科技','600076.SH':'康欣新材',
 '301575.SZ':'艾芬达','605598.SH':'上海港湾',
 # 三模型融合榜
 '001225.SZ':'和泰机电','688377.SH':'迪威尔','603585.SH':'苏利股份','300818.SZ':'耐普矿机',
 '300854.SZ':'中兰环保','300982.SZ':'苏文电能','301382.SZ':'复洁科技',
 # 10d独立榜
 '002961.SZ':'瑞达期货','300120.SZ':'经纬辉开','300413.SZ':'芒果超媒','000668.SZ':'荣丰控股',
 '605580.SH':'恒盛能源','600551.SH':'时代出版','600825.SH':'新华传媒','688356.SH':'键凯科技',
 # 中枢版+三模型 重评日候选
 '688659.SH':'元琛科技','003027.SZ':'同兴科技','300500.SZ':'启迪设计','688607.SH':'康众科技',
 '002875.SZ':'安奈儿','603382.SH':'海阳科技','300556.SZ':'丝路视觉','300908.SZ':'仲景食品',
 '301050.SZ':'雷电微力',
 # 中枢版Top10
 '002763.SZ':'汇洁股份','301507.SZ':'民生健康','600645.SH':'中源协和','603797.SH':'联泰环保',
 '300239.SZ':'东宝生物','688083.SH':'中望软件','301370.SZ':'国科恒泰','301203.SZ':'国泰环保',
 '603273.SH':'天元智能','603080.SH':'新疆火炬',
 # CMMR+三模型融合候选
 '300970.SZ':'华绿生物','600262.SH':'北方股份','300614.SZ':'百川畅银','300621.SZ':'维业股份',
 '301156.SZ':'美农生物','688435.SH':'英方软件','603810.SH':'丰山集团','002809.SZ':'红墙股份',
 # CMMR独立榜
 '000019.SZ':'深粮控股','000020.SZ':'深华发A','000426.SZ':'兴业银锡','000505.SZ':'京粮控股',
 '000523.SZ':'红棉股份','000713.SZ':'国投丰乐','000715.SZ':'中兴商业','000716.SZ':'黑芝麻',
 '000735.SZ':'罗牛山','000751.SZ':'锌业股份',
}

conn = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = list(WATCH)
inlist = ','.join(f"'{c}'" for c in codes)
rows = conn.execute(f"""
  SELECT ts_code, trade_date, close, pct_chg FROM daily
  WHERE ts_code IN ({inlist}) AND trade_date >= '20260815'
  ORDER BY ts_code, trade_date
""").fetchall()

by = {}
for ts, d, c, p in rows:
    by.setdefault(ts, []).append((d, c, p if p is not None else 0.0))

# ledger costs
lc = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
hold = {r[0]: r for r in lc.execute("SELECT code, shares, avg_cost, latest_price, stop_loss, target_price FROM holdings WHERE status='hold'").fetchall()}

out = []
for ts in codes:
    seq = by.get(ts, [])
    if not seq:
        out.append({'code': ts, 'name': WATCH[ts], 'err': 'no daily rows'}); continue
    closes = [s[1] for s in seq]
    last_d, last_c = seq[-1][0], closes[-1]
    c5 = closes[-1]/closes[-6]-1 if len(closes) >= 6 else None
    c3 = closes[-1]/closes[-4]-1 if len(closes) >= 4 else None
    c1 = closes[-1]/closes[-2]-1 if len(closes) >= 2 else None
    hi20 = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    dhi = closes[-1]/hi20-1
    updays = sum(1 for s in seq[-3:] if s[2] > 0)
    rec = {'code': ts, 'name': WATCH[ts], 'last_date': last_d, 'close': round(last_c,2),
           'p1': round(c1*100,1) if c1 is not None else None,
           'p3': round(c3*100,1) if c3 is not None else None,
           'p5': round(c5*100,1) if c5 is not None else None,
           'dist_hi20': round(dhi*100,1), 'up_days_3': updays}
    if ts in hold:
        v, cp, cur, sl, tp = hold[ts][1], hold[ts][2], hold[ts][3], hold[ts][4], hold[ts][5]
        rec['led_vol'], rec['led_cost'], rec['led_cur'] = v, cp, cur
        rec['led_pnl_pct'] = round((cur/cp-1)*100,1) if cp else None
        rec['stop_loss'], rec['target_price'] = sl, tp
    out.append(rec)

print(json.dumps(out, ensure_ascii=False, indent=0))
# 最近交易日确认
print('MAX_TRADE_DATE', conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
