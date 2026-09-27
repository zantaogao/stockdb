# v8 三模型融合权重网格回测（2026-09-27）
# 方法：对验证段（各链 split_date 起）逐票生成 v8 三模型预测，
#       评估各权重组合的 日度 RankIC（对前向10/20/40日收益）+ NW-t 显著性 + 层内收益
import itertools, numpy as np, pandas as pd, duckdb, time, json
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
OUT = BASE / 'fusion_grid'
OUT.mkdir(exist_ok=True)

print('加载模型与样本...', flush=True)
m10 = lgb.Booster(model_str=(BASE/'lgb_reg_10d_v8.txt').read_text())
m20 = lgb.Booster(model_str=(BASE/'lgb_reg_20d_v8.txt').read_text())
m40 = lgb.Booster(model_str=(BASE/'lgb_reg_40d_v8.txt').read_text())

d10 = pd.read_parquet(BASE/'samples_10d.parquet')
d20 = pd.read_parquet(BASE/'samples_20d.parquet')
d40 = pd.read_parquet(BASE/'samples_40d.parquet')
print(f'样本 {len(d10):,} / {len(d20):,} / {len(d40):,}', flush=True)

# 预测窗口 = 三链验证段交集
lo = max('20250304','20250220','20250121')  # 10d切分最晚
pred_start, pred_end = lo, '20260730'  # 40d末端（+40日需<=cal末端，见下裁）
t0=time.time()
p10 = m10.predict(d10[d10.date>=pred_start].iloc[:, 2:33].values)
p20 = m20.predict(d20[d20.date>=pred_start].iloc[:, 2:33].values)
p40 = m40.predict(d40[d40.date>=pred_start].iloc[:, 2:31].values)
df10 = d10[d10.date>=pred_start][['date','code']].copy(); df10['p10']=p10
df20 = d20[d20.date>=pred_start][['date','code']].copy(); df20['p20']=p20
df40 = d40[d40.date>=pred_start][['date','code']].copy(); df40['p40']=p40
print(f'预测完成 {time.time()-t0:.0f}s', flush=True)

df = df10.merge(df20, on=['date','code']).merge(df40, on=['date','code'])
print(f'融合样本(交集) {len(df):,}', flush=True)

# 真实前向收益（对齐用）
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
cal = [str(r[0]) for r in con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
cal_idx = {d:i for i,d in enumerate(cal)}
end_i = cal_idx['20260924']
# 评估日：date+40 <= 末端（保证40d成熟）；且>=pred_start
eval_dates = [d for d in sorted(df.date.unique()) if cal_idx.get(d) is not None and cal_idx[d]+40 <= end_i and d>=pred_start]
print(f'评估日 {len(eval_dates)} 天 {eval_dates[0]}~{eval_dates[-1]}', flush=True)
df = df[df.date.isin(eval_dates)]

# 前向价格
codes = df.code.unique()
ts_of = lambda c: c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')
code2ts = {c: ts_of(c) for c in codes}
df['ts'] = df.code.map(code2ts)

# 拉所有评估日及+10/+20/+40日的close
eds = set(eval_dates)
for n in (10,20,40):
    eds |= {cal[cal_idx[d]+n] for d in eval_dates}
eds = sorted(eds)
in_list = ",".join(f"'{t}'" for t in df.ts.unique())
date_in = ",".join(f"'{d}'" for d in eds)
t0=time.time()
px = con.execute(f"SELECT ts_code, trade_date, close FROM daily WHERE ts_code IN ({in_list}) AND trade_date IN ({date_in})").fetchall()
pxmap = {}
for ts,d,c in px: pxmap[(ts,str(d))] = float(c)
print(f'价格 {len(px):,} 条 {time.time()-t0:.0f}s', flush=True)

# 逐评估日收益向量
day_data = {}
for d in eval_dates:
    sub = df[df.date==d]
    d0 = d
    f10d, f20d, f40d = cal[cal_idx[d]+10], cal[cal_idx[d]+20], cal[cal_idx[d]+40]
    rows = []
    for ts,p1,p2,p4 in zip(sub.ts, sub.p10, sub.p20, sub.p40):
        b = pxmap.get((ts,d0))
        a,c,e = pxmap.get((ts,f10d)), pxmap.get((ts,f20d)), pxmap.get((ts,f40d))
        if b and a and c and e and b>0:
            rows.append((p1,p2,p4,a/b-1,c/b-1,e/b-1))
    if len(rows) >= 1000:
        day_data[d] = np.array(rows)
print(f'有效评估日 {len(day_data)}', flush=True)

# 网格: w10+w20+w40=1 步长0.05
grid = [(round(a,2),round(b,2),round(1-a-b,2)) for a in np.arange(0,1.0001,0.05) for b in np.arange(0,1.0001-a,0.05)]
print(f'权重组合 {len(grid)}', flush=True)
res = []
ds = sorted(day_data)
for (a,b,c) in grid:
    ic10,ic20,ic40,icfus = [],[],[],[]
    for d in ds:
        arr = day_data[d]
        fus = a*arr[:,0]+b*arr[:,1]+c*arr[:,2]
        ic10.append(stats.spearmanr(fus,arr[:,3])[0])
        ic20.append(stats.spearmanr(fus,arr[:,4])[0])
        ic40.append(stats.spearmanr(fus,arr[:,5])[0])
        icfus.append(stats.spearmanr(fus,arr[:,4])[0])  # 主KPI=20日IC
    res.append(dict(w10=a,w20=b,w40=c,
        ic10=np.mean(ic10),ic20=np.mean(ic20),ic40=np.mean(ic40),
        t20=stats.ttest_1samp(icfus,0)[0]))
rdf = pd.DataFrame(res).sort_values('ic20', ascending=False)
rdf.to_csv(OUT/'grid_results.csv', index=False)
print(rdf.head(15).to_string(index=False))
print('--- 单模型参考 ---')
solo={}
for name,col in [('p10',0),('p20',1),('p40',2)]:
    ic10s=[stats.spearmanr(day_data[d][:,col],day_data[d][:,3])[0] for d in ds]
    ic20s=[stats.spearmanr(day_data[d][:,col],day_data[d][:,4])[0] for d in ds]
    ic40s=[stats.spearmanr(day_data[d][:,col],day_data[d][:,5])[0] for d in ds]
    solo[name]=(np.mean(ic10s),np.mean(ic20s),np.mean(ic40s))
    print(f"{name}: 10日IC {np.mean(ic10s):+.4f} 20日IC {np.mean(ic20s):+.4f} 40日IC {np.mean(ic40s):+.4f}")
json.dump({'eval_days':len(ds),'solo':{k:[float(x) for x in v] for k,v in solo.items()}}, open(OUT/'meta.json','w'))
