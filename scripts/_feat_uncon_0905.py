# 非常规特征批量IC验证 0905
# 全市场截面 Spearman IC vs 未来10日收益，分年份 t 检验
import duckdb, numpy as np, pandas as pd

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
START = '20240601'   # 特征暖机起点
EVAL_START = '20250101'

c = duckdb.connect(DB, read_only=True)

daily = c.execute(f"""
  select ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol, amount
  from daily where trade_date >= '{START}'
""").df()

adj = c.execute(f"select ts_code, trade_date, adj_factor from adj_factor where trade_date >= '{START}'").df()
dbsc = c.execute(f"""
  select ts_code, trade_date, turnover_rate, circ_mv
  from daily_basic where trade_date >= '{START}'
""").df()
lim = c.execute(f"select ts_code, trade_date, up_limit, down_limit from stk_limit where trade_date >= '{START}'").df()
mf = c.execute(f"""
  select stock_code as symbol, strftime(date,'%Y%m%d') as trade_date, main_net, retail_net
  from money_flow where date >= DATE '2024-06-01'
""").df()
nine = c.execute(f"""
  select ts_code, trade_date, up_count, down_count, nine_up_turn, nine_down_turn
  from stk_nineturn where trade_date >= '{START}'
""").df()
hn = c.execute("""
  select ts_code, ann_date, end_date, try_cast(holder_num as bigint) as holder_num
  from stk_holdernumber where ann_date >= '20240101' and holder_num is not null
""").df()
c.close()

daily['symbol'] = daily.ts_code.str[:6]
daily = daily.sort_values(['ts_code','trade_date']).reset_index(drop=True)

# 复权价与前向收益
daily = daily.merge(adj, on=['ts_code','trade_date'], how='left')
g = daily.groupby('ts_code')
daily['adjclose'] = daily.close * daily.adj_factor
daily['fwd10'] = g.adjclose.transform(lambda s: s.shift(-10)/s - 1)

daily = daily.merge(dbsc, on=['ts_code','trade_date'], how='left')
daily = daily.merge(lim, on=['ts_code','trade_date'], how='left')
daily = daily.merge(mf, on=['symbol','trade_date'], how='left')
daily = daily.merge(nine, on=['ts_code','trade_date'], how='left')

g = daily.groupby('ts_code', sort=False)

# ---- F1 距涨停价距离 ----
daily['f1_uplimit_dist'] = (daily.up_limit - daily.close) / daily.close * 100

# 触板/封板/炸板
touched = (daily.high >= daily.up_limit*0.998) & daily.up_limit.notna()
sealed  = (daily.close  >= daily.up_limit*0.998) & daily.up_limit.notna()
daily['_touch'] = touched.astype(float); daily['_seal'] = sealed.astype(float)
daily['_zba_touch'] = (touched & ~sealed).astype(float)
g = daily.groupby('ts_code', sort=False)
daily['f2_touch_freq20'] = g._touch.transform(lambda s: s.rolling(20,min_periods=10).sum())
tb = g._zba_touch.transform(lambda s: s.rolling(20,min_periods=5).sum())
tt = g._touch.transform(lambda s: s.rolling(20,min_periods=5).sum())
daily['f3_zhaban_rate20'] = np.where(tt>0, tb/tt.replace(0,np.nan), np.nan)

# F4 下影线承接力（量加权20日）
rng = (daily.high - daily.low).replace(0, np.nan)
wick = (daily[['open','close']].min(axis=1) - daily.low) / rng
daily['_wick'] = wick
daily['_wv'] = wick * daily.vol
g = daily.groupby('ts_code', sort=False)
num = g._wv.transform(lambda s: s.rolling(20,min_periods=10).sum())
den = g.vol.transform(lambda s: (s*wick.notna()).rolling(20,min_periods=10).sum())
daily['f4_wick_absorb20'] = num/den.replace(0,np.nan)

# F5 主力助推效率：10日涨幅 / (10日主力净流入/流通市值%)
cmv = daily.circ_mv.replace(0,np.nan)
daily['_mf_pctmv'] = daily.main_net / cmv * 100
g = daily.groupby('ts_code', sort=False)
r10 = g.pct_chg.transform(lambda s: s.rolling(10,min_periods=8).sum())
m10 = g._mf_pctmv.transform(lambda s: s.rolling(10,min_periods=8).sum())
daily['f5_money_eff10'] = r10 / (m10.abs() + 0.05) * np.sign(m10.replace(0,np.nan))

# F7/F8 九转
daily['f7_up_count'] = daily.up_count
nine_turn = daily[daily.nine_up_turn==1][['ts_code','trade_date']]
daily['_nt'] = np.where(daily.nine_up_turn==1, daily.trade_date.astype(int), np.nan)
def days_since(s):
    x = s.copy()
    last = np.nan; out=[]
    for v in x.values:
        if not np.isnan(v): last = v
        out.append(v if False else (np.nan if np.isnan(last) else None))
    return out
# 向量化替代：ffill 后与当日差
daily['_ntf'] = daily.groupby('ts_code',sort=False)._nt.transform(lambda s: s.ffill())
daily['f8_days_since_nineup'] = (daily.trade_date.astype(float) - daily._ntf).clip(upper=30)
daily.loc[daily._ntf.isna(),'f8_days_since_nineup'] = 30

# F9 浮盈抛压：close>当日均价 的20日占比（amount千元 vol手 → 均价=amount*10/vol）
avgp = daily.amount*10/daily.vol.replace(0,np.nan)
above = (daily.close > avgp).astype(float)
daily['_above'] = above
daily['f9_profit_days20'] = daily.groupby('ts_code',sort=False)._above.transform(lambda s: s.rolling(20,min_periods=10).mean())

# F10 上涨日/下跌日量能比20
upv = daily.vol.where(daily.pct_chg>0, 0.0); dnv = daily.vol.where(daily.pct_chg<0, 0.0)
daily['_upv']=upv; daily['_dnv']=dnv
g=daily.groupby('ts_code',sort=False)
un = g._upv.transform(lambda s: s.rolling(20,min_periods=10).sum())
dn = g._dnv.transform(lambda s: s.rolling(20,min_periods=10).sum())
daily['f10_uv_asym20'] = np.log((un+1)/(dn+1))

# F11 量价背离：corr(pct_chg, turnover_rate) 20日
daily['_ptr'] = daily.pct_chg * daily.turnover_rate
g=daily.groupby('ts_code',sort=False)
pmean = g.pct_chg.transform(lambda s: s.rolling(20,min_periods=15).mean())
tmean = g.turnover_rate.transform(lambda s: s.rolling(20,min_periods=15).mean())
mxy= g._ptr.transform(lambda s: s.rolling(20,min_periods=15).mean())
vx = g.pct_chg.transform(lambda s: s.rolling(20,min_periods=15).var())
vy = g.turnover_rate.transform(lambda s: s.rolling(20,min_periods=15).var())
daily['f11_pv_corr20'] = (mxy - pmean*tmean)/np.sqrt(vx*vy).replace(0,np.nan)

# F12 主力净流入连续天数（带符号）
pos = (daily.main_net>0).astype(int); neg = (daily.main_net<0).astype(int)
def streak(x, sgn):
    arr = x.values; out=np.zeros(len(arr)); run=0.0
    for i,v in enumerate(arr):
        run = run+1 if v==1 else 0
        out[i]=run*sgn
    return out
daily['f12_main_streak'] = streak(pos,1) + streak(neg,-1)

# F13 主力散户分歧
daily['f13_mr_diverge'] = (daily.main_net - daily.retail_net)/cmv*100

# F14 涨停基因120日
daily['_sealf']=sealed.astype(float)
daily['f14_limit_gene120'] = daily.groupby('ts_code',sort=False)._sealf.transform(lambda s: s.rolling(120,min_periods=60).sum())

# F15 向上未回补缺口敞口（逐票循环）
def gap_exposure(dfg):
    o=dfg.open.values; l=dfg.low.values; pc=dfg.pre_close.values
    n=len(dfg); out=np.full(n,np.nan)
    gaps=[]  # (idx, bottom)
    for i in range(n):
        if o[i] > pc[i]*1.002: gaps.append([i, pc[i]])
        gaps = [gg for gg in gaps if i-gg[0] <= 10]
        opened = sum(1 for j,b in gaps if l[i] <= b)
        gaps = [gg for gg in gaps if not (l[i] <= gg[1])]
        idxs = [j for j,_ in gaps]
        out[i] = sum(1 for j,b in gaps if i-j>=0)*0  # placeholder
        # 敞口 = 未回补缺口数 × 平均缺口幅度
        if gaps:
            amp = np.mean([(b-o[j])/b for j,b in gaps])
            out[i] = len(gaps)*amp*100
        else: out[i]=0.0
    return pd.Series(out, index=dfg.index)
ge = daily.groupby('ts_code', group_keys=False).apply(gap_exposure)
daily['f15_gap_exposure'] = ge

# F6 股东户数变化速率：ann_date as-of（asof join on ann_date<=trade_date），环比%/年化
hn = hn.sort_values(['ts_code','ann_date','end_date']).drop_duplicates(['ts_code','ann_date'],keep='last')
hn['_chg'] = hn.groupby('ts_code').holder_num.pct_change()*100
hn['_gap'] = (pd.to_datetime(hn.ann_date)-pd.to_datetime(hn.end_date)).dt.days  # 披露滞后天数，信息
# 两次公告间变化速率%/月
hn['_prev_end'] = hn.groupby('ts_code').end_date.shift()
d1 = pd.to_datetime(hn.end_date); d0 = pd.to_datetime(hn._prev_end)
days = (d1-d0).dt.days.replace(0,np.nan)
hn['_rate_mo'] = hn._chg / days * 30.4
hnj = hn[['ts_code','ann_date','_rate_mo']].rename(columns={'ann_date':'trade_date'})
hnj = hnj.sort_values(['trade_date'])
daily['_td'] = pd.to_datetime(daily.trade_date)
hnj['_td'] = pd.to_datetime(hnj.trade_date)
m = pd.merge_asof(daily.sort_values('_td'), hnj.sort_values('_td'),
                  by='ts_code', on='_td', direction='backward', tolerance=pd.Timedelta('400D'))
daily['f6_holder_rate_mo'] = m._rate_mo.values

FEATS = ['f1_uplimit_dist','f2_touch_freq20','f3_zhaban_rate20','f4_wick_absorb20',
         'f5_money_eff10','f6_holder_rate_mo','f7_up_count','f8_days_since_nineup',
         'f9_profit_days20','f10_uv_asym20','f11_pv_corr20','f12_main_streak',
         'f13_mr_diverge','f14_limit_gene120','f15_gap_exposure',
         'bench_ret10']
g=daily.groupby('ts_code',sort=False)
daily['bench_ret10'] = g.pct_chg.transform(lambda s: s.rolling(10,min_periods=8).sum())

ev = daily[(daily.trade_date>=EVAL_START) & daily.fwd10.notna()].copy()
# 过滤：剔新股（不足60交易日）
cnt = ev.groupby('ts_code').trade_date.transform('count')
ev = ev[cnt>=60]
# 剔北交所
ev = ev[~ev.ts_code.str.endswith('.BJ')]
print('eval rows:', len(ev), 'days:', ev.trade_date.nunique(), flush=True)

FEATS = [f for f in FEATS if f in ev.columns]
ev = ev.replace([np.inf,-np.inf], np.nan)

# 逐日截面 rank IC
rows=[]
for f in FEATS:
    sub = ev[['trade_date',f,'fwd10']].dropna(subset=[f])
    ics={}
    for (f2,) in []: pass
    grp = sub.groupby('trade_date')
    ics = grp.apply(lambda d: d[f].rank().corr(d['fwd10'].rank()) if len(d)>=100 else np.nan, include_groups=False)
    s = ics.dropna()
    for yr in ['2025','2026']:
        ss = s[s.index.str[:4]==yr]
        if len(ss)>20:
            t = ss.mean()/ss.std()*np.sqrt(len(ss))
            rows.append(dict(feat=f, year=yr, n_days=len(ss), mean_ic=round(ss.mean(),4),
                             t=round(t,2), win=round((ss>0).mean(),3)))
r = pd.DataFrame(rows).sort_values(['feat','year'])
pd.set_option('display.width',200)
print(r.to_string(index=False))
r.to_csv('/Users/zantao/.hermes/stockdb/analysis/uncon_feat_ic_0905.csv',index=False)
print('saved -> analysis/uncon_feat_ic_0905.csv')