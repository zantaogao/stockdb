# 事件驱动信号初筛：业绩预告/回购公告后10日超额（分年+t检验）
import duckdb, numpy as np, pandas as pd

c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# 日线（2024-06起，用于算前向收益与市场等权基准）
d = c.execute("""
    select ts_code, trade_date, close from daily
    where trade_date >= '20240601' order by ts_code, trade_date
""").df()
d['idx'] = d.groupby('ts_code').cumcount()
# 前向10日收益
d['close10'] = d.groupby('ts_code')['close'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['close10'] / d['close'] - 1
# 市场等权基准（当日全体可算前向收益的票均值）
bench = d.dropna(subset=['fwd10']).groupby('trade_date')['fwd10'].mean().rename('mkt')
d = d.join(bench, on='trade_date')
d['exc10'] = d['fwd10'] - d['mkt']
fwd = d.set_index(['ts_code', 'trade_date'])[['fwd10', 'exc10']]

# ST/北交所过滤
bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])

def event_study(ev, label, group_cols):
    """ev: df with ts_code, ann_date(+分组列). 按(ts_code,ann_date)去重取当日最新公告"""
    ev = ev.drop_duplicates(subset=['ts_code', 'ann_date'], keep='last')
    ev = ev[~ev['ts_code'].isin(bad)]
    m = fwd.reindex(pd.MultiIndex.from_arrays([ev['ts_code'], ev['ann_date']]))
    ev = ev.assign(**{k: m[k].values for k in ['fwd10', 'exc10']}).dropna(subset=['exc10'])
    ev['year'] = ev['ann_date'].str[:4]
    print(f'\n===== {label} =====  有效事件 {len(ev)}')
    for g, sub in ev.groupby(group_cols if isinstance(group_cols, list) else [group_cols], dropna=True):
        for yr, s in sub.groupby('year'):
            if len(s) < 30: continue
            t = s['exc10'].mean() / (s['exc10'].std() / np.sqrt(len(s)))
            print(f"  {g} {yr}: n={len(s):5d}  10d超额均值={s['exc10'].mean()*100:+.2f}%  t={t:+.1f}  胜率={(s['exc10']>0).mean()*100:.0f}%")

# 1) 业绩预告：按预告类型（2024/2025 两个完整年度）
fc = c.execute("""
    select ts_code, coalesce(nullif(f_ann_date,''), ann_date) as ann_date, type,
           (try_cast(p_change_min as double)+try_cast(p_change_max as double))/2 as pchg
    from forecast where ann_date between '20240601' and '20251231'
""").df()
event_study(fc, '业绩预告 按类型', 'type')

# 2) 预增类按增幅分档
pos = fc[fc['type'].isin(['预增','略增','续盈','扭亏'])].copy()
pos['bucket'] = pd.cut(pos['pchg'], [-100, 0, 50, 100, 300, 10000],
                       labels=['<=0','0-50%','50-100%','100-300%','>300%'])
event_study(pos, '预增/略增/续盈/扭亏 按增幅', 'bucket')

# 3) 回购公告（事件当天）
rp = c.execute("""
    select ts_code, ann_date from repurchase
    where ann_date between '20240601' and '20251231'
""").df()
event_study(rp, '回购公告（全体）', lambda x: 'ALL')
