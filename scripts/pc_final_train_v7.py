"""
LightGBM v7 — 2020~2026 全周期 + 分类专用特征
33维: 23基础 + 4GTJA + 6分类专用(RSI/BB%/连涨连跌/量价背离/相对强度)

对比v6:
  - 回归模型不变（27维）
  - 分类模型新增6维方向信号（33维）
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, json
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
print("加载日线数据 (2019-06 ~ 2026-06)...", flush=True)
daily = con.execute("""
    SELECT stock_code, date, open, close, high, low,
           change_pct/100.0 as ret, amount, volume
    FROM stock_daily WHERE date >= '2019-06-01' ORDER BY stock_code, date
""").fetchdf()
val_df = con.execute(
    "SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation"
).fetchdf()

# 预计算市场日均收益（用于相对强度）
print("计算市场基准收益...", flush=True)
market_ret = con.execute("""
    SELECT date, AVG(change_pct) as avg_ret 
    FROM stock_daily WHERE date >= '2019-06-01' AND change_pct IS NOT NULL
    GROUP BY date ORDER BY date
""").fetchdf()
market_ret['cum_5d'] = market_ret['avg_ret'].rolling(5, min_periods=5).sum()
mkt_5d_map = dict(zip(market_ret['date'].astype(str), market_ret['cum_5d']))
con.close()

vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

# GTJA panel
panel = {}
for col in ['open','close','high','low','volume','amount','ret']:
    panel[col] = daily.pivot_table(index='date', columns='stock_code', values=col)
panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
print(f"  Panel: {panel['close'].shape[0]}天 × {panel['close'].shape[1]}只", flush=True)

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

# ── 特征生成 ──
print("\n特征生成 (2020~2026, 33维)...", flush=True)
rows = []; cc = 0
MIN_TRAIN_DATE = '2020-01-01'
min_ts = pd.Timestamp(MIN_TRAIN_DATE)

# Tracks consecutive up/down days per stock
consec_up = 0; consec_down = 0; prev_ret = 0

for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=np.nan_to_num(grp['close'].values.astype(np.float64))
    r_arr=np.nan_to_num(grp['ret'].values.astype(np.float64))
    a_arr=np.nan_to_num(grp['amount'].values.astype(np.float64))
    v_arr=np.nan_to_num(grp['volume'].values.astype(np.float64))
    d_arr=grp['date'].values
    if n<120: continue; cc+=1
    consec_up=0; consec_down=0; prev_ret=0
    for i in range(119, n):
        if d_arr[i] < min_ts: continue
        
        c=c_arr[:i+1]; lc=c[-1]; r=r_arr[:i+1]; v=v_arr[:i+1]
        cur_ret = r[i]
        
        # ── 23基础特征（同v6）──
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
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); lc2=v.get('ln_cap',22)
        
        # ── 4个GTJA因子 ──
        dt_str = str(d_arr[i])[:10]
        gtja_v = []
        for gn in GTJA_NAMES:
            sig = gtja_results.get(gn)
            if sig is not None and dt_str in sig.index and code in sig.columns:
                val = sig.loc[dt_str, code]
                gtja_v.append(float(val) if not np.isnan(val) else 0.0)
            else: gtja_v.append(0.0)
        
        # ── 6个分类专用特征 ──
        
        # 1. RSI-14
        if len(r) >= 15:
            r14 = r[-15:]
            gains = np.maximum(r14, 0)
            losses = np.maximum(-r14, 0)
            ag = np.mean(gains)
            al = np.mean(losses)
            rsi = 100 - 100 / (1 + ag/al) if al > 0 else 100
        else:
            rsi = 50
        
        # 2. 布林带 %B
        ma20 = np.mean(c[-20:])
        std20_bb = np.std(c[-20:])
        upper = ma20 + 2*std20_bb
        lower = ma20 - 2*std20_bb
        bb_pct = (lc - lower) / (upper - lower) if upper != lower else 0.5
        
        # 3. 连涨/连跌天数
        if cur_ret > 0:
            consec_up += 1
            consec_down = 0
        elif cur_ret < 0:
            consec_down += 1
            consec_up = 0
        else:
            consec_up = 0; consec_down = 0
        con_up = min(consec_up, 20)  # cap at 20
        con_down = min(consec_down, 20)
        
        # 4. 量价背离（20日价格与量变化的相关性）
        if len(r) >= 20 and len(v) >= 21:
            pr_chg = r[-20:]
            vl_chg = v[-20:] / v[-21:-1] - 1  # volume day-over-day change
            if np.std(pr_chg) > 0 and np.std(vl_chg) > 0:
                vol_div = np.corrcoef(pr_chg, vl_chg)[0,1]
            else:
                vol_div = 0
        else:
            vol_div = 0
        
        # 5. 相对大盘强度（5日超额收益）
        stock_5d = np.prod(1 + r[-5:]) - 1 if len(r) >= 5 else 0
        mkt_5d = mkt_5d_map.get(dt_str, 0)
        rel_str = stock_5d - mkt_5d
        
        # 未来5日收益（标签）
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        
        # ── 33维特征（27基础+GTJA + 6分类专用）──
        base_feat = [chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,lc2]+gtja_v
        cls_feat = [rsi/100, bb_pct, con_up/20, con_down/20, vol_div, rel_str*20]
        
        rows.append(np.array(base_feat + cls_feat + [rf], dtype=np.float32))
    
    if cc%500==0: print(f"  {cc}只 {len(rows):,}样本", flush=True)

arr=np.array(rows)
X_all=arr[:,:-1]; y=arr[:,-1]; y_cls=(y>0).astype(int)
X_all=np.nan_to_num(X_all, nan=0.0)
print(f"\n总样本: {len(X_all):,}  特征: {X_all.shape[1]}维  正样本率: {y_cls.mean():.1%}", flush=True)

# ── 80/20时间切分 ──
split=int(len(X_all)*0.8)
X_tr, X_te = X_all[:split], X_all[split:]
y_tr, y_te = y[:split], y[split:]
y_tr_c, y_te_c = y_cls[:split], y_cls[split:]
print(f"训练: {len(X_tr):,}  测试: {len(X_te):,}", flush=True)

# ── 回归模型用前27维，分类用33维 ──
X_reg_tr = X_tr[:, :27]; X_reg_te = X_te[:, :27]
X_cls_tr = X_tr; X_cls_te = X_te  # 分类用全部33维

# ── 标准化（回归27维 / 分类33维分开保存）──
def normalize_and_save(X_part, n_dims, name):
    stats = {}
    for j in range(n_dims):
        col=X_part[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
        m,s=np.nanmean(col),np.nanstd(col)
        stats[f'feat_{j}'] = {'mean': float(m), 'std': float(s), 'low': float(l), 'high': float(h)}
        if s>0: X_part[:,j]=(col-m)/s
    return X_part, stats

X_reg_tr, reg_norm = normalize_and_save(X_reg_tr, 27, 'reg')
X_reg_te = X_reg_te.copy()
for j in range(27):
    s=reg_norm.get(f'feat_{j}',{})
    if s and s['std']>0: X_reg_te[:,j]=(np.clip(X_reg_te[:,j],s['low'],s['high'])-s['mean'])/s['std']

X_cls_tr, cls_norm = normalize_and_save(X_cls_tr, 33, 'cls')
X_cls_te = X_cls_te.copy()
for j in range(33):
    s=cls_norm.get(f'feat_{j}',{})
    if s and s['std']>0: X_cls_te[:,j]=(np.clip(X_cls_te[:,j],s['low'],s['high'])-s['mean'])/s['std']

X_reg_te=np.nan_to_num(X_reg_te); X_cls_te=np.nan_to_num(X_cls_te)

json.dump(reg_norm, open(f"{OUT}/v7_norm_reg.json",'w'))
json.dump(cls_norm, open(f"{OUT}/v7_norm_cls.json",'w'))
print("标准化统计量已保存", flush=True)

# ── 回归模型（27维，同v6）──
print("\n训练回归模型 (27维)...", flush=True)
reg = lgb.LGBMRegressor(
    n_estimators=3000, max_depth=6, num_leaves=63,
    learning_rate=0.03, min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
    reg_alpha=0.1, reg_lambda=0.1, random_state=42, n_jobs=4,
    device='gpu', gpu_platform_id=0, gpu_device_id=0, verbose=-1)
reg.fit(X_reg_tr, y_tr,
    eval_set=[(X_reg_te, y_te)], eval_metric='l2',
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])

pred_reg = reg.predict(X_reg_te)
reg_ic = stats.spearmanr(pred_reg, y_te)[0]
print(f"回归 IC={reg_ic:.4f}  树数={reg.best_iteration_}", flush=True)

# ── 分类模型（33维含专用特征）──
print("\n训练分类模型 (33维)...", flush=True)
cls = lgb.LGBMClassifier(
    n_estimators=2000, max_depth=8, num_leaves=127,
    learning_rate=0.01, min_child_samples=30, subsample=0.7, colsample_bytree=0.7,
    reg_alpha=0.1, reg_lambda=0.1, scale_pos_weight=1.0,
    random_state=42, n_jobs=4,
    device='gpu', gpu_platform_id=0, gpu_device_id=0, verbose=-1)
cls.fit(X_cls_tr, y_tr_c,
    eval_set=[(X_cls_te, y_te_c)], eval_metric='auc',
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])

pred_cls = cls.predict_proba(X_cls_te)[:,1]
cls_auc = roc_auc_score(y_te_c, pred_cls)
print(f"分类 AUC={cls_auc:.4f}  树数={cls.best_iteration_}", flush=True)

# 验证：reg方向AUC
auc_reg_dir = roc_auc_score(y_te_c, pred_reg)
print(f"回归方向 AUC: {auc_reg_dir:.4f}", flush=True)

# ── 保存模型 ──
reg.booster_.save_model(f"{OUT}/lgb_reg_v7.txt")
cls.booster_.save_model(f"{OUT}/lgb_cls_v7.txt")
print(f"\n模型已保存", flush=True)

# ── 回测验证 ──
print(f"\n=== 回测验证 ===")
print(f"  回归 IC: {reg_ic:.4f}")
print(f"  回归方向 AUC: {auc_reg_dir:.4f}")
print(f"  分类 AUC: {cls_auc:.4f}")
print(f"  分类准确率: {(pred_cls.round()==y_te_c).mean():.2%}")

df = pd.DataFrame({'pred': pred_reg, 'ret': y_te})
df['decile'] = pd.qcut(df['pred'].rank(), 10, labels=False, duplicates='drop')
grp = df.groupby('decile')['ret'].mean()
spread = grp.iloc[-1] - grp.iloc[0] if len(grp) > 1 else 0
mono = all(grp.iloc[i] <= grp.iloc[i+1] for i in range(len(grp)-1)) if len(grp) > 1 else False
print(f"  分组多空差: {spread*100:+.2f}%")
print(f"  分组单调性: {'通过' if mono else '不通过'}")

result = {
    'data_range': '2020-01~2026-06',
    'n_features_reg': 27, 'n_features_cls': 33,
    'n_train': int(len(X_tr)), 'n_test': int(len(X_te)),
    'reg_ic': round(float(reg_ic), 4),
    'reg_trees': reg.best_iteration_,
    'cls_auc': round(float(cls_auc), 4),
    'cls_trees': cls.best_iteration_,
    'reg_dir_auc': round(float(auc_reg_dir), 4),
    'decile_spread': round(float(spread*100), 2),
    'monotonic': mono,
    'total_time': int(time.time()-t0),
    'device': 'cuda',
    'date': time.strftime('%Y-%m-%d'),
}
json.dump(result, open(f"{OUT}/final_results_v7.json",'w'), indent=2)
print(f"\n总耗时: {result['total_time']}s", flush=True)
print(json.dumps(result, indent=2), flush=True)
