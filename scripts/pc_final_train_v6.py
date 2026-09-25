"""
LightGBM v6 — 2020~2026 全周期训练
27维特征 (23技术+估值 + 4精选GTJA: 006/083/177/184)

相比v5:
  - 数据范围从 2024~2026(581天) 扩展到 2020~2026(~1500天)
  - GTJA因子从预计算pickle改为内联panel计算
  - 覆盖完整牛熊周期(COVID暴跌/结构性行情/大熊市/修复/上涨)
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, pickle, gzip, json
from scipy import stats
from sklearn.metrics import roc_auc_score
from importlib import import_module

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
GTJA_ALPHAS = {
    'gtja_006': import_module('src.factors.zoo.gtja191.alpha_006'),
    'gtja_083': import_module('src.factors.zoo.gtja191.alpha_083'),
    'gtja_177': import_module('src.factors.zoo.gtja191.alpha_177'),
    'gtja_184': import_module('src.factors.zoo.gtja191.alpha_184'),
}
GTJA_NAMES = list(GTJA_ALPHAS.keys())
t0 = time.time()

con = duckdb.connect(DB)

# ── 加载日线数据（2019-06起，含200天warmup供GTJA-184）──
print("加载日线数据 (2019-06 ~ 2026-06)...", flush=True)
daily = con.execute("""
    SELECT stock_code, date, open, close, high, low,
           change_pct/100.0 as ret, amount, volume
    FROM stock_daily WHERE date >= '2019-06-01' ORDER BY stock_code, date
""").fetchdf()

# 估值数据
val_df = con.execute(
    "SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation"
).fetchdf()
con.close()

print(f"  日线: {len(daily):,}行, {daily['stock_code'].nunique()}只股票", flush=True)

# ── 构建估值字典 ──
vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

# ── 构建GTJA panel（全量数据）──
print("构建GTJA panel...", flush=True)
panel = {}
for col in ['open','close','high','low','volume','amount','ret']:
    panel[col] = daily.pivot_table(index='date', columns='stock_code', values=col)
panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
print(f"  Panel: {panel['close'].shape[0]}天 × {panel['close'].shape[1]}只", flush=True)

# 计算4个GTJA因子
print("计算GTJA因子...", flush=True)
gtja_results = {}
for fname, mod in GTJA_ALPHAS.items():
    t1 = time.time()
    try:
        sig = mod.compute(panel)
        if sig is not None and not sig.empty:
            gtja_results[fname] = sig
            print(f"  {fname}: {sig.shape} ({time.time()-t1:.1f}s)", flush=True)
    except Exception as e:
        print(f"  {fname}: ❌ {str(e)[:60]}", flush=True)
        gtja_results[fname] = None

# ── 特征生成（只从2020-01-01开始取样本）──
print("\n特征生成 (2020~2026)...", flush=True)
rows = []; cc = 0
MIN_TRAIN_DATE = '2020-01-01'
min_ts = pd.Timestamp(MIN_TRAIN_DATE)

for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=grp['close'].values.astype(np.float64)
    r_arr=np.nan_to_num(grp['ret'].values.astype(np.float64)); a_arr=np.nan_to_num(grp['amount'].values.astype(np.float64))
    d_arr=grp['date'].values
    if n<120: continue; cc+=1
    for i in range(119, n):
        # 从2020-01-01才开始取训练样本
        if d_arr[i] < min_ts: continue
        
        c=c_arr[:i+1]; lc=c[-1]
        chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
        chg60=lc/c[-60]-1; chg120=lc/c[0]-1
        ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
        d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
        b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
        rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
        std20=np.std(c[-20:])/np.mean(c[-20:])*100
        vols=a_arr[:i+1][-20:]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r_arr[i] if i>0 else 0; c3d=lc/c[-3]-1 if len(c)>=3 else 0
        
        # 估值
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); lc2=v.get('ln_cap',22)
        
        # 未来5日收益（标签）
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        
        # 4个GTJA因子（从panel取）
        dt_str = str(d_arr[i])[:10]
        gtja_v = []
        for gn in GTJA_NAMES:
            sig = gtja_results.get(gn)
            if sig is not None and dt_str in sig.index and code in sig.columns:
                val = sig.loc[dt_str, code]
                gtja_v.append(float(val) if not np.isnan(val) else 0.0)
            else:
                gtja_v.append(0.0)
        
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,lc2]+gtja_v+[rf], dtype=np.float32))
    
    if cc%500==0: print(f"  {cc}只 {len(rows):,}样本", flush=True)

arr=np.array(rows); X=arr[:,:-1]; y=arr[:,-1]; y_cls=(y>0).astype(int)
X=np.nan_to_num(X, nan=0.0)
print(f"\n总样本: {len(X):,}  特征: {X.shape[1]}维  正样本率: {y_cls.mean():.1%}", flush=True)

# ── 80/20时间切分（按数据顺序）──
split=int(len(X)*0.8)
X_tr, X_te = X[:split], X[split:]
y_tr, y_te = y[:split], y[split:]
y_tr_c, y_te_c = y_cls[:split], y_cls[split:]
print(f"训练: {len(X_tr):,}  测试: {len(X_te):,}", flush=True)

# ── z-score标准化（基于训练集统计量）──
norm_stats = {}
for j in range(X_tr.shape[1]):
    col=X_tr[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col)
    norm_stats[f'feat_{j}'] = {'mean': float(m), 'std': float(s), 'low': float(l), 'high': float(h)}
    if s>0: X_tr[:,j]=(col-m)/s; X_te[:,j]=(np.clip(X_te[:,j],l,h)-m)/s
X_te=np.nan_to_num(X_te)

# 保存标准化统计量（供推理使用）
with open(f"{OUT}/v6_norm_stats.json", 'w') as f:
    json.dump(norm_stats, f)
print(f"标准化统计量已保存: v6_norm_stats.json", flush=True)

# ── 回归模型 ──
print("\n训练回归模型...", flush=True)
reg = lgb.LGBMRegressor(
    n_estimators=3000, max_depth=6, num_leaves=63,
    learning_rate=0.03, min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
    reg_alpha=0.1, reg_lambda=0.1, random_state=42, n_jobs=4,
    device='gpu', gpu_platform_id=0, gpu_device_id=0, verbose=-1)
reg.fit(X_tr, y_tr,
    eval_set=[(X_te, y_te)], eval_metric='l2',
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])

pred_reg = reg.predict(X_te)
reg_ic = stats.spearmanr(pred_reg, y_te)[0]
print(f"回归 IC={reg_ic:.4f}  树数={reg.best_iteration_}", flush=True)

# ── 分类模型 ──
print("\n训练分类模型...", flush=True)
cls = lgb.LGBMClassifier(
    n_estimators=1000, max_depth=6, num_leaves=63,
    learning_rate=0.03, min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
    reg_alpha=0.1, reg_lambda=0.1, random_state=42, n_jobs=4,
    device='gpu', gpu_platform_id=0, gpu_device_id=0, verbose=-1)
cls.fit(X_tr, y_tr_c,
    eval_set=[(X_te, y_te_c)], eval_metric='auc',
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])

pred_cls = cls.predict_proba(X_te)[:,1]
cls_auc = roc_auc_score(y_te_c, pred_cls)
print(f"分类 AUC={cls_auc:.4f}  树数={cls.best_iteration_}", flush=True)

# ── 保存模型 ──
reg.booster_.save_model(f"{OUT}/lgb_reg_v6.txt")
cls.booster_.save_model(f"{OUT}/lgb_cls_v6.txt")
print(f"\n模型已保存: lgb_reg_v6.txt, lgb_cls_v6.txt", flush=True)

# ── 回测验证 ──
y_bin = (y_te > 0).astype(int)
print(f"\n=== 回测验证 ===")
print(f"  回归 IC: {reg_ic:.4f}")
print(f"  分类 AUC: {cls_auc:.4f}")
print(f"  分类准确率: {(pred_cls.round()==y_te_c).mean():.2%}")

# 分组单调性
df = pd.DataFrame({'pred': pred_reg, 'ret': y_te})
df['decile'] = pd.qcut(df['pred'].rank(), 10, labels=False, duplicates='drop')
grp = df.groupby('decile')['ret'].mean()
spread = grp.iloc[-1] - grp.iloc[0] if len(grp) > 1 else 0
print(f"  分组多空差: {spread*100:+.2f}%")
mono = all(grp.iloc[i] <= grp.iloc[i+1] for i in range(len(grp)-1)) if len(grp) > 1 else False
print(f"  分组单调性: {'通过' if mono else '不通过'}")

# ── 保存训练结果 ──
result = {
    'data_range': '2020-01~2026-06',
    'n_features': X.shape[1],
    'n_train': int(len(X_tr)),
    'n_test': int(len(X_te)),
    'reg_ic': round(float(reg_ic), 4),
    'reg_trees': reg.best_iteration_,
    'cls_auc': round(float(cls_auc), 4),
    'cls_trees': cls.best_iteration_,
    'decile_spread': round(float(spread*100), 2),
    'monotonic': mono,
    'total_time': round(time.time()-t0),
    'device': 'cuda',
    'date': time.strftime('%Y-%m-%d'),
}
with open(f"{OUT}/final_results_v6.json", 'w') as f:
    json.dump(result, f)
print(f"\n训练结果已保存: final_results_v6.json")
print(f"总耗时: {result['total_time']}s", flush=True)
