#!/usr/bin/env python3
# 步骤2.5 持仓与榜内票日线核验 2026-09-29
import duckdb, sqlite3, json

codes_hold = {  # 主账户持仓
 '002454.SZ':'松芝股份','603202.SH':'天有为','600076.SH':'康欣新材','605598.SH':'上海港湾',
 '300658.SZ':'延江股份','603966.SH':'法兰泰克','603811.SH':'诚意药业','301093.SZ':'华兰股份',
 '301283.SZ':'聚胶股份','301237.SZ':'和顺科技','688093.SH':'世华科技','688186.SH':'广大特材',
 '001332.SZ':'锡装股份','300854.SZ':'中兰环保','601615.SH':'明阳智能','300651.SZ':'金陵体育',
 '301575.SZ':'艾芬达'}
codes_board = {  # 榜内拟点名票
 '600547.SH':'山东黄金','603226.SH':'菲林格尔','600499.SH':'科达制造','002545.SZ':'东方铁塔',
 '688629.SH':'华丰科技','600363.SH':'联创光电','002625.SZ':'光启技术','002961.SH':'瑞达期货',
 '688117.SH':'圣诺生物','001225.SZ':'和泰机电','000550.SZ':'江铃汽车','300822.SZ':'贝仕达克',
 '301070.SZ':'开勒股份','603099.SH':'长白山','603201.SH':'常润股份','002595.SZ':'豪迈科技',
 '300724.SZ':'捷佳伟创','688217.SH':'睿昂基因','301130.SZ':'西点药业','688793.SH':'倍轻松'}

allc = {**codes_hold, **codes_board}
q = ",".join(f"'{c}'" for c in allc)
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
rows = con.execute(f"""
  SELECT ts_code, trade_date, close, pct_chg FROM daily
  WHERE ts_code IN ({q}) AND trade_date >= '20260820'
  ORDER BY ts_code, trade_date
""").fetchall()
con.close()

by = {}
for ts, d, c, p in rows:
    by.setdefault(ts, []).append((d, c, p))

lc = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
hold = {r[0]: r for r in lc.execute("SELECT code, name, avg_cost, shares, latest_price, stop_loss FROM holdings").fetchall()}
lc.close()

out = []
for ts, name in allc.items():
    h = by.get(ts, [])
    if len(h) < 6:
        out.append(f"{name} {ts}: 日线不足({len(h)})")
        continue
    closes = [x[1] for x in h]
    last = closes[-1]; lastd = h[-1][0]
    c5 = closes[-6]
    chg5 = (last/c5-1)*100
    hi20 = max(closes[-20:]) if len(closes)>=20 else max(closes)
    dist_hi = (last/hi20-1)*100
    # consecutive up days (ending last)
    up = 0
    for d,c,p in reversed(h):
        if p is not None and p > 0: up += 1
        else: break
    dn = 0
    for d,c,p in reversed(h):
        if p is not None and p < 0: dn += 1
        else: break
    chg3 = (last/closes[-4]-1)*100 if len(closes)>=4 else None
    lastpct = h[-1][2]
    tag = "持仓" if ts in codes_hold else "榜内"
    line = f"{tag} {name} {ts} 收{last}({lastd}) 当日{lastpct:+.2f}% 5日{chg5:+.2f}% 3日{chg3:+.2f}% 距20日高{dist_hi:+.2f}% 连涨{up}/连跌{dn}"
    key = ts.split('.')[0]
    if key in hold:
        _, nm, cost, qty, cur, sl = hold[key]
        line += f" | 成本{cost} 现价{cur} 市值{cur*qty:,.0f} 止损线{sl}"
    out.append(line)
print("\n".join(out))
