# -*- coding: utf-8 -*-
# cmmr 缺陷统计（2026-09-20）
# 用 signal_history（cmmr_score+old_score 等）+ tushare.db daily 自算 pct_chg_10d / ma40_slope，
# 按整档分组（离散6档铁律，禁止十分位）验证设计矛盾：高分档到底是不是"超卖"票
import duckdb, sqlite3, numpy as np, pandas as pd

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score from signal_history where date>='20260715'", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]
sh['datef'] = sh['date'].str[:4]+'-'+sh['date'].str[4:6]+'-'+sh['date'].str[6:8]
print('signal_history 行数', len(sh), '日期', sh['date'].min(), '->', sh['date'].max())

du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
# 日线（后复权：close*adj_factor）2026-05-01 起，供 ma40/slope/pct_chg_10d
px = du.execute("""
  select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c, d.open*a.adj_factor as o, d.vol as v
  from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
  where d.trade_date >= '20260401'
""").df()
px = px.sort_values(['code','dt'])
g = px.groupby('code')
px['ma40'] = g['c'].transform(lambda s: s.rolling(40).mean())
px['ma40_l20'] = g['ma40'].transform(lambda s: s.shift(20))
px['slope'] = (px['ma40']-px['ma40_l20'])/px['ma40_l20']
px['chg10'] = g['c'].transform(lambda s: s/s.shift(10)-1)
px['vol_ratio'] = g['v'].transform(lambda s: s/s.rolling(20).mean())
px['date'] = px['dt'].str[:4]+'-'+px['dt'].str[4:6]+'-'+px['dt'].str[6:8]
px['code6'] = px['code'].str[:6]

m = sh.drop(columns=['date']).rename(columns={'datef':'date'}).merge(
    px[['code6','date','c','o','slope','chg10','vol_ratio']], left_on=['stock_code','date'], right_on=['code6','date'])
print('merge 后', len(m), '天覆盖', m['date'].nunique())

# 档位构成：每档里 chg10 分布 + slope 分布 —— 验证"高分=超卖"是否成立
print()
print('=== 各档构成（票-日）===')
for grade, sub in m.groupby('cmmr_score'):
    print('档%3d n=%7d | 前10日涨幅: 为负占比%4.0f%% 中位%+6.2f%% P90%+6.2f%% | slope>0.02占比%3.0f%% | vol_ratio<0.8占比%3.0f%% >1.2占比%3.0f%%' % (
        grade, len(sub), (sub['chg10']<0).mean()*100, sub['chg10'].median()*100,
        sub['chg10'].quantile(0.9)*100, (sub['slope']>0.02).mean()*100,
        (sub['vol_ratio']<0.8).mean()*100, (sub['vol_ratio']>1.2).mean()*100))

# 理论档位矩阵：trend(40/20/0) x oversold(40/20/0) x vol(20/0) 实际出现频率
m['trend'] = np.where(m['slope']>0.02, 40, np.where(m['slope']>0, 20, 0))
m['os'] = np.where(m['chg10']<-0.08, 40, np.where(m['chg10']<-0.04, 20, 0))
m['vol'] = np.where((m['vol_ratio']<0.8) | ((m['vol_ratio']>1.2)&(m['c']>m['o'])), 20, 0)
m2 = m[m['cmmr_score']>0]
m['recon'] = np.where(m['slope']<0, 0, m['trend']+m['os']+m['vol'])
agree = (m['recon']==m['cmmr_score']).mean()*100
print('重算cmmr_score与signal_history一致率: %.1f%%（<90%%则本脚本口径与生产不同，结论存疑）' % agree)
print()
print('=== >0分票的三维构成 ===')
print(m2.groupby(['trend','os','vol']).size().sort_values(ascending=False).head(12))
print()
print('trend=40 且 oversold>0 的占比: %.1f%%' % ((m2['trend']==40)&(m2['os']>0)).mean()*100)
# 80+ 档里"前10日实际下跌"占比 = 超卖本意兑现率
hi = m[m['cmmr_score']>=80]
print('80+档中前10日涨幅为负占比: %.1f%%（若低=高分票根本不是超卖票）' % ((hi['chg10']<0).mean()*100))
lo = m[(m['cmmr_score']>=40)&(m['cmmr_score']<80)]
print('40-60档中前10日涨幅为负占比: %.1f%%' % ((lo['chg10']<0).mean()*100))

# 各档前向超额（逐日扣全市场等权），20d 口径
fwd = px.copy()
fwd['fwd20'] = fwd.groupby('code')['c'].transform(lambda s: s.shift(-20)/s-1)
mktall = fwd.groupby('date')['fwd20'].mean().rename('mkt').reset_index()
f = fwd[['code6','date','fwd20']].rename(columns={'date':'datef'})
m = m.merge(f, left_on=['stock_code','date'], right_on=['code6','datef'], suffixes=('','_f')).drop_duplicates(subset=['stock_code','date','cmmr_score'])
m['ex'] = m['fwd20'] - m['date'].map(mktall.set_index('date')['fwd20'])
print()
print('=== 各档20d超额（逐日扣等权）===')
for grade, sub in m.groupby('cmmr_score'):
    byday = sub.groupby('date')['ex'].mean()
    print('档%3d n=%7d 日均超额%+6.2f%% 为正天数 %d/%d' % (grade, len(sub), byday.mean()*100, (byday>0).sum(), len(byday)))
