# 深挖三个未测维度：①机构新进前十大流通 ②股息率/估值百分位 ③分钟线覆盖盘点
import duckdb, numpy as np, pandas as pd

c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

d = c.execute("""
    select ts_code, trade_date, close from daily
    where trade_date >= '20240101' order by ts_code, trade_date
""").df()
d['close10'] = d.groupby('ts_code')['close'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['close10'] / d['close'] - 1
bench = d.dropna(subset=['fwd10']).groupby('trade_date')['fwd10'].mean().rename('mkt')
d = d.join(bench, on='trade_date')
d['exc10'] = d['fwd10'] - d['mkt']
fwd = d.dropna(subset=['exc10']).set_index(['ts_code', 'trade_date'])['exc10']

bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])

def summarize(ev, label):
    ev = ev[~ev['ts_code'].isin(bad)].dropna(subset=['exc10'])
    ev['year'] = ev['ann_date'].str[:4]
    print(f'\n===== {label} ===== n={len(ev)}')
    for yr, s in ev.groupby('year'):
        if len(s) < 30: continue
        t = s['exc10'].mean() / (s['exc10'].std() / np.sqrt(len(s)))
        print(f"  {yr}: n={len(s):5d}  10d超额={s['exc10'].mean()*100:+.2f}%  t={t:+.1f}  胜率={(s['exc10']>0).mean()*100:.0f}%")

# ① 聪明钱新进前十大流通（汇金/社保/QFII/券商自营？先只取汇金+社保+外资QFII名单词根）
SMART = ['中央汇金','全国社保','社保基金','养老金','MORGANSTANLEY','GOLDMAN','高盛','UBS','摩根','QFII','瑞士银行']
th = c.execute("""
    select ts_code, ann_date, end_date, holder_name from top10_floatholders
    where ann_date >= '20240101'
""").df()
th['smart'] = th['holder_name'].str.upper().apply(lambda h: any(k.upper() in h for k in SMART))
print('聪明钱持仓记录占比:', th['smart'].mean().round(4), ' 涉及股票数:', th[th['smart']]['ts_code'].nunique())
# 事件=该 smart holder 本期出现、上期(end_date更早一期)不在该股前十大
evs = []
for ts, g in th.groupby('ts_code'):
    g = g.sort_values(['end_date', 'ann_date'])
    seen = {}
    for ed, sub in g.groupby('end_date'):
        cur = set(sub[sub['smart']]['holder_name'])
        prev_eds = sorted([e for e in seen if e < ed])
        prev = set()
        if prev_eds:
            pe = prev_eds[-1]
            prev = set(seen[pe][1])
        fresh = cur - prev
        if fresh:
            row = sub[sub['holder_name'].isin(fresh)].sort_values('ann_date').iloc[0]
            evs.append((ts, str(row['ann_date'])))
        seen[ed] = (sub['ann_date'].max(), list(set(sub['holder_name'])))
ev1 = pd.DataFrame(evs, columns=['ts_code', 'ann_date'])
ev1 = ev1[ev1['ann_date'] >= '20240101'].drop_duplicates()
m = fwd.reindex(pd.MultiIndex.from_arrays([ev1['ts_code'], ev1['ann_date']]))
ev1['exc10'] = m.values
summarize(ev1, '① 聪明钱新进前十大流通（公告日入场）')

# ② 股息率/估值截面IC（月度取截面 rank IC vs fwd10，2024/2025 分年）
va = c.execute("""
    select ts_code, trade_date, pe_ttm, pb, dv_ttm, total_mv
    from daily_basic where trade_date >= '20240101' and trade_date <= '20251231'
""").df()
d2 = d.dropna(subset=['exc10'])
va = va.merge(d2[['ts_code','trade_date','exc10']], on=['ts_code','trade_date'])
va['size'] = np.log(va['total_mv'].clip(lower=1))
for col in ['dv_ttm','pe_ttm','pb','size']:
    sub = va.dropna(subset=[col])
    ic = sub.groupby('trade_date').apply(lambda g: g[col].corr(g['exc10'], method='spearman') if len(g)>100 else np.nan, include_groups=False)
    ic = ic.dropna()
    for yr in ['2024','2025']:
        s = ic[ic.index.str[:4]==yr]
        t = s.mean()/(s.std()/np.sqrt(len(s)))
        print(f"② {col} 10d截面IC {yr}: 均值={s.mean():+.4f}  t={t:+.1f}  正率={(s>0).mean()*100:.0f}% (n={len(s)})")

# 高股息多头组合：dv_ttm>4 vs 市场
hi = va.dropna(subset=['dv_ttm'])
hi = hi.assign(ym=hi['trade_date'].str[:6])
print('\n② 高股息(>4%)月度截面超额:')
for ym, g in hi[hi['dv_ttm']>4].groupby('ym'):
    yr = ym[:4]
    if yr not in ('2024','2025'): continue
    print(f"  {ym}: n={len(g):4d} 超额={g['exc10'].mean()*100:+.2f}%", end='')
    if len(g)>=100 and int(ym[-2])%2==1: print(' |', end='')
print()
