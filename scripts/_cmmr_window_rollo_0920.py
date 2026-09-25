# -*- coding: utf-8 -*-
# cmmr 重评窗对拍：10d滚动 vs 20d持有（组合级，非队列起点口径）
# 池=signal_history cmmr>=80；键序与账户一致 cmmr DESC, fusion DESC；等权 top10
import sqlite3, duckdb, numpy as np, pandas as pd
sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score, fusion_score from signal_history where cmmr_score>=80", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]
print('信号历史覆盖', sh['date'].nunique(), '天', sh['date'].min(), '~', sh['date'].max())
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""
  select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
  from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
  where d.trade_date >= '20260501'""").df().sort_values(['code','dt'])
px['code6'] = px['code'].str[:6]
piv = px.pivot_table(index='dt', columns='code6', values='c', aggfunc='last')
du.close()
alldays = sorted(piv.index)
sigdays = sorted(d for d in sh['date'].unique() if d in piv.index)

def ret64(code, d0, d1):
    try:
        c0, c1 = piv.at[d0, code], piv.at[d1, code]
        if pd.isna(c0) or pd.isna(c1) or c0<=0: return np.nan
        return c1/c0-1
    except Exception: return np.nan

def roll(win):
    """从 sigdays[0] 起，每 win 个交易日换一次仓（gap 模式：重新按键序选 top10）"""
    entry = sigdays[0]
    i = alldays.index(entry); legs = []
    while True:
        j = i + win
        if j >= len(alldays): break
        d1 = alldays[j]
        day = sh[sh['date']==entry]
        day = day.sort_values(['cmmr_score','fusion_score'], ascending=False)
        codes = day['stock_code'].tolist()[:10]
        rr = [ret64(c, entry, d1) for c in codes]
        rr = [r for r in rr if not pd.isna(r)]
        if not rr: break
        legs.append((entry, d1, np.mean(rr), len(rr)))
        entry, i = d1, j
    return legs

out = {}
for w in (10, 20):
    legs = roll(w)
    nav = np.prod([1+l[2] for l in legs]) - 1
    out[w] = legs
    print('\n=== %dd 滚动: %d 段 ===' % (w, len(legs)))
    for e,d1,r,n in legs:
        print('  %s→%s  %+6.2f%% (%d只)' % (e, d1, r*100, n))
    print('  区间累计 %+6.2f%%  段胜率 %d/%d' % (nav*100, sum(1 for l in legs if l[2]>0), len(legs)))

# 等长公共区间对拍：取两策略都覆盖的 [start, min(end10,end20)]
if 10 in out and 20 in out and out[10] and out[20]:
    common_end = min(out[10][-1][1], out[20][-1][1])
    def nav_to(legs, end):
        nav=1.0
        for e,d1,r,n in legs:
            if d1 <= end: nav *= 1+r
            else:
                # 该段跨过 end：按时间比例截断近似
                i0,i1 = alldays.index(e), alldays.index(d1)
                k = min(alldays.index(end), i1)
                frac = (k-i0)/(i1-i0) if i1>i0 else 0
                nav *= 1 + r*frac
                break
        return nav-1
    n10, n20 = nav_to(out[10], common_end), nav_to(out[20], common_end)
    print('\n=== 公共区间 %s~%s: 10d滚动 %+5.2f%% vs 20d持有 %+5.2f%% ===' % (sigdays[0], common_end, n10*100, n20*100))
# 换手成本敏感度：每次换仓按单边0.15%（佣金+冲击+隔日摩擦）计，10d滚动换仓次数是20d的两倍
for w in (10,20):
    if w in out and out[w]:
        cost = (len(out[w])-1)*0.003  # 双边0.3%/次，首段不计
        nav = np.prod([1+l[2] for l in out[w]])-1
        print('  %dd滚动 扣换手成本%.2f%%后 %+5.2f%%' % (w, cost*100, ((1+nav)/(1+cost)-1)*100 if cost else nav*100))
