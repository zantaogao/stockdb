# -*- coding: utf-8 -*-
# cmmr 深究 v3（0920）：同分构成解剖 / 衰减曲线 / 消融对拍 / 市况条件化
# 统一键：6位码 + YYYYMMDD；复权价自算（与 defect2 一致，一致率曾实锤 80.6%）
import sqlite3, duckdb, numpy as np, pandas as pd

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score, fusion_score from signal_history where cmmr_score is not null and date>='20260701'", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]

du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""
  select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c,
         d.open*a.adj_factor as o, d.vol as v
  from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
  where d.trade_date >= '20260301'
""").df().sort_values(['code','dt'])
g = px.groupby('code')
px['ma40'] = g['c'].transform(lambda s: s.rolling(40).mean())
px['ma40_l20'] = g['ma40'].transform(lambda s: s.shift(20))
px['slope'] = (px['ma40']-px['ma40_l20'])/px['ma40_l20']
px['chg10'] = g['c'].transform(lambda s: s/s.shift(10)-1)
px['vol_ratio'] = g['v'].transform(lambda s: s/s.rolling(20).mean())
for h in (1,3,5,10,15,20):
    px[f'fwd{h}'] = g['c'].transform(lambda s, h=h: s.shift(-h)/s-1)
px['code6'] = px['code'].str[:6]
du.close()

m = sh.merge(px[['code6','dt','c','o','slope','chg10','vol_ratio','fwd1','fwd3','fwd5','fwd10','fwd15','fwd20']],
             left_on=['stock_code','date'], right_on=['code6','dt'])
mkt = {h: px.groupby('dt')[f'fwd{h}'].mean() for h in (1,3,5,10,15,20)}
for h in (1,3,5,10,15,20):
    m[f'ex{h}'] = m[f'fwd{h}'] - m['date'].map(mkt[h])
# 自算维度（解剖用这套，口径与训练/打分脚本同源）
m['tr'] = np.where(m['slope']>0.02, 40, np.where(m['slope']>0, 20, 0))
m['os'] = np.where(m['chg10']<-0.08, 40, np.where(m['chg10']<-0.04, 20, 0))
m['vo'] = np.where((m['vol_ratio']<0.8)|((m['vol_ratio']>1.2)&(m['c']>m['o'])), 20, 0)
print('匹配 %d 行 %d 天 (%s~%s)' % (len(m), m['date'].nunique(), m['date'].min(), m['date'].max()))

print()
print('=== ① 同分构成解剖：80分/100分池里各(tr,os,vo)组合的真实前向 ===')
m80p = m[m['cmmr_score']>=80].copy()
m80p['combo'] = m80p['tr'].astype(int).astype(str)+'/'+m80p['os'].astype(int).astype(str)+'/'+m80p['vo'].astype(int).astype(str)
for sc, sub in m80p.groupby('cmmr_score'):
    print('-- 档位 %d（n=%d）' % (sc, len(sub)))
    for combo, c2 in sub.groupby('combo'):
        d10 = c2.groupby('date')['ex10'].mean().dropna()
        d20 = c2.groupby('date')['ex20'].mean().dropna()
        print('   %-10s n=%6d 日均票%4d | 10d超额 %+5.2f%%(%d天) | 20d超额 %+5.2f%%(%d天)' % (
            combo, len(c2), len(c2)/max(1,c2['date'].nunique()),
            d10.mean()*100 if len(d10) else np.nan, len(d10),
            d20.mean()*100 if len(d20) else np.nan, len(d20)))

print()
print('=== ② 持有期衰减：cmmr>=80 池的 ex1/3/5/10/15/20 逐日等权均值 ===')
for h in (1,3,5,10,15,20):
    d = m80p.groupby('date')[f'ex{h}'].mean().dropna()
    print('  fwd%-2d 超额日均 %+5.2f%%  正天 %d/%d' % (h, d.mean()*100, (d>0).sum(), len(d)))
print('  对照：全池(>0分)')
m0 = m[m['cmmr_score']>0]
for h in (1,5,10,20):
    d = m0.groupby('date')[f'ex{h}'].mean().dropna()
    print('  fwd%-2d 超额日均 %+5.2f%%  正天 %d/%d' % (h, d.mean()*100, (d>0).sum(), len(d)))

print()
print('=== ③ 消融对拍（逐日配对差 + NW-t lag10）：80+池 top10 按fusion选 vs 随机10只 vs 全池 ===')
def nw_t(x, lag=10):
    x = np.asarray(x); n=len(x)
    if n < lag+3: return np.nan
    mu = x.mean(); e = x-mu
    s = np.var(x, ddof=1)/n
    for l in range(1, lag+1):
        cov = (e[l:]*e[:-l]).mean()
        s += 2*cov*(1-l/(lag+1))/n
    return mu/np.sqrt(s)*np.sqrt(n) if s>0 else np.nan
rng = np.random.default_rng(7)
days = []
for dt, sub in m80p.groupby('date'):
    if len(sub) < 15: continue
    s20 = sub.dropna(subset=['fwd20'])
    if len(s20) < 15: continue
    top = s20.nlargest(10, 'fusion_score')
    rnd = s20.sample(10, random_state=abs(hash(dt))%2**31)
    days.append((dt, top['ex20'].mean(), rnd['ex20'].mean(), s20['ex20'].mean(),
                 s20['ex20'].nsmallest(10).mean()))
dd = pd.DataFrame(days, columns=['date','top10','rand10','pool','bot10'])
for name in ('top10','rand10','bot10'):
    dif = dd[name]-dd['pool']
    print('  %-6s vs 池: 日差 %+5.2f%% NW-t %+5.2f 正天 %d/%d' % (name, dif.mean()*100, nw_t(dif), (dif>0).sum(), len(dif)))
dif = dd['top10']-dd['rand10']
print('  fusion-top10 vs 池内随机10: 日差 %+5.2f%% NW-t %+5.2f 正天 %d/%d  ← fusion次级键的真实增量' % (dif.mean()*100, nw_t(dif), (dif>0).sum(), len(dif)))

print()
print('=== ④ 市况条件化：80+池日超额 vs 当日全市场等权fwd1（U形/状态过滤定位）===')
pxm = px.drop_duplicates('dt').set_index('dt')
m80p['mkt_fwd20'] = m80p['date'].map(px.groupby('dt')['fwd20'].mean())
q = m80p.dropna(subset=['fwd20','mkt_fwd20'])
qs = pd.qcut(q['mkt_fwd20'], 4, labels=['弱市Q1','Q2','Q3','强市Q4'])
q['q'] = qs
for qq, sub in q.groupby('q', observed=True):
    d = sub.groupby('date')['ex20'].mean().dropna()
    print('  %s (市况20d前瞻四分位): 80+池超额日均 %+5.2f%%  正天 %d/%d  日均池宽 %d' % (
        qq, d.mean()*100, (d>0).sum(), len(d), len(sub)/max(1,sub['date'].nunique())))

print()
print('=== ⑤ 100分 vs 80分 配对（同交易日对比）===')
rows=[]
for dt, sub in m80p.groupby('date'):
    a = sub[sub['cmmr_score']==100].dropna(subset=['fwd20'])
    b = sub[sub['cmmr_score']==80].dropna(subset=['fwd20'])
    if len(a)>=5 and len(b)>=5:
        rows.append((dt, a['ex20'].mean(), b['ex20'].mean(), len(a), len(b)))
if rows:
    r = pd.DataFrame(rows, columns=['date','a','b','na','nb'])
    dif = r['a']-r['b']
    print('  100分池-80分池: 日差 %+5.2f%% NW-t %+5.2f 正天 %d/%d' % (dif.mean()*100, nw_t(dif), (dif>0).sum(), len(dif)))
