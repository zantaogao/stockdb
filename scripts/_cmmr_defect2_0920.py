# -*- coding: utf-8 -*-
# cmmr 缺陷统计 v2（2026-09-20，干净重写）
# 统一键：stock_code 6位 + date 'YYYY-MM-DD'
import duckdb, sqlite3, numpy as np, pandas as pd

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score from signal_history where date>='20260715'", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]

du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""
  select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c,
         d.open*a.adj_factor as o, d.vol as v
  from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
  where d.trade_date >= '20260401'
""").df().sort_values(['code','dt'])
g = px.groupby('code')
px['ma40'] = g['c'].transform(lambda s: s.rolling(40).mean())
px['ma40_l20'] = g['ma40'].transform(lambda s: s.shift(20))
px['slope'] = (px['ma40']-px['ma40_l20'])/px['ma40_l20']
px['chg10'] = g['c'].transform(lambda s: s/s.shift(10)-1)
px['vol_ratio'] = g['v'].transform(lambda s: s/s.rolling(20).mean())
px['fwd20'] = g['c'].transform(lambda s: s.shift(-20)/s-1)
px['fwd10'] = g['c'].transform(lambda s: s.shift(-10)/s-1)
px['code6'] = px['code'].str[:6]

m = sh.merge(px[['code6','dt','c','o','slope','chg10','vol_ratio','fwd20','fwd10']],
             left_on=['stock_code','date'], right_on=['code6','dt'])
m = m.rename(columns={'dt':'pdate'})
m['date'] = m['date'].astype(str)
print('信号-行情 匹配', len(m), '天', m['date'].nunique())

# 全市场等权基准（每日）
mkt20 = px.groupby('dt')['fwd20'].mean()
mkt10 = px.groupby('dt')['fwd10'].mean()
m['ex20'] = m['fwd20'] - m['date'].map(mkt20)
m['ex10'] = m['fwd10'] - m['date'].map(mkt10)

print()
print('=== 各档构成（离散6档铁律）===')
for grade, sub in m.groupby('cmmr_score'):
    print('档%3d n=%7d | 前10日涨幅: 为负占比%3.0f%% 中位%+6.2f%% | slope>0.02占比%3.0f%% | volR<0.8占比%3.0f%% | 20d超额 日均%+5.2f%% 正天%d/%d | 10d超额 %+5.2f%%' % (
        grade, len(sub), (sub['chg10']<0).mean()*100, sub['chg10'].median()*100,
        (sub['slope']>0.02).mean()*100, (sub['vol_ratio']<0.8).mean()*100,
        sub.groupby('date')['ex20'].mean().mean()*100,
        (sub.groupby('date')['ex20'].mean()>0).sum(), sub['date'].nunique(),
        sub.groupby('date')['ex10'].mean().mean()*100))

# 三维构成矩阵
m['trend'] = np.where(m['slope']>0.02, 40, np.where(m['slope']>0, 20, 0))
m['os'] = np.where(m['chg10']<-0.08, 40, np.where(m['chg10']<-0.04, 20, 0))
m['vols'] = np.where((m['vol_ratio']<0.8) | ((m['vol_ratio']>1.2)&(m['c']>m['o'])), 20, 0)
m['recon'] = np.where(m['slope']<0, 0, m['trend']+m['os']+m['vols'])
agree = (m['recon']==m['cmmr_score']).mean()*100
print()
print('重算一致率 %.1f%%（复权价口径差致小幅出入可接受，>75%% 即档构成统计可用）' % agree)
m2 = m[m['cmmr_score']>0]
print('>0分票中 trend=40（强势股）且 oversold>0（超卖）共现占比: %.1f%%' % (((m2['trend']==40)&(m2['os']>0)).mean()*100))
print('>0分票总量中 oversold 贡献>0 的占比: %.1f%%' % ((m2['os']>0).mean()*100))
# 高分档的池子随时间稳定性：80+ 池每日数量
hi = m[m['cmmr_score']>=80]
print('80+池 每日只数: 中位 %d 范围 %d-%d（池子大小=行情函数）' % (
    hi.groupby('date').size().median(), hi.groupby('date').size().min(), hi.groupby('date').size().max()))
# 80+池内部分化：按fusion次级键劈半（复现0911结论于新窗口）
if 'old_score' not in sh.columns:
    pass
# 80+池 20d 超额按 10d 内路径: 前5日 vs 全20日
print()
print('=== 80+池 逐月 20d超额 ===')
hi_m = hi.assign(ym=hi['date'].str[:6]).groupby('ym').apply(
    lambda d: (d.groupby('date')['ex20'].mean().mean()*100, len(d)), include_groups=False)
for ym,(v,n) in hi_m.items(): print(' %s 日均超额%+5.2f%% (n=%d)' % (ym, v, n))
print()
print('=== 100档 vs 80档 分解: 100=80+vol20, 80=os40+slope40 ===')
for grade in (60, 80, 100):
    sub = m[m['cmmr_score']==grade]
    bd = sub.groupby('date')['ex20'].mean().dropna()
    print('档%d: 日均超额%+5.2f%% 正天%d/%d' % (grade, bd.mean()*100, (bd>0).sum(), len(bd)))
print()
print('DONE')
