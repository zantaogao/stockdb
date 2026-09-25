"""
Quick check: reg AUC as direction classifier
Uses the already-computed test set from training
"""
import json, numpy as np, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from scipy import stats

OUT = r"C:\Users\pumma\factor_lib"

# Load models
reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v6.txt")
cls = lgb.Booster(model_file=f"{OUT}/lgb_cls_v6.txt")
norm = json.load(open(f"{OUT}/v6_norm_stats.json"))

# Load test data that was used in training
# Reconstruct features from stock.db (same logic as training, but ONLY test period)
import duckdb, numpy as np, pandas as pd
from importlib import import_module

GTJA_ALPHAS = {
    'gtja_006': import_module('src.factors.zoo.gtja191.alpha_006'),
    'gtja_083': import_module('src.factors.zoo.gtja191.alpha_083'),
    'gtja_177': import_module('src.factors.zoo.gtja191.alpha_177'),
    'gtja_184': import_module('src.factors.zoo.gtja191.alpha_184'),
}
GTJA_NAMES = list(GTJA_ALPHAS.keys())

con = duckdb.connect(OUT + "/stock.db")
daily = con.execute("""
    SELECT stock_code, date, open, close, high, low,
           change_pct/100.0 as ret, amount, volume
    FROM stock_daily WHERE date >= '2019-06-01' ORDER BY stock_code, date
""").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
con.close()

vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

panel = {}
for col in ['open','close','high','low','volume','amount','ret']:
    panel[col] = daily.pivot_table(index='date', columns='stock_code', values=col)
panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)

gtja_results = {}
for fname, mod in GTJA_ALPHAS.items():
    try:
        sig = mod.compute(panel)
        if sig is not None and not sig.empty: gtja_results[fname] = sig
    except: gtja_results[fname] = None

# Get split date
all_dates = sorted(daily['date'].unique())
split_idx = int(len(all_dates) * 0.8)
split_date = all_dates[split_idx]

print(f"Split: {all_dates[0]}~{split_date} / {all_dates[-1]} ({len(all_dates)-split_idx} test days)")

rows = []; cc = 0
for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=np.nan_to_num(grp['close'].values.astype(np.float64))
    r_arr=np.nan_to_num(grp['ret'].values.astype(np.float64))
    a_arr=np.nan_to_num(grp['amount'].values.astype(np.float64))
    d_arr=grp['date'].values
    if n<120: continue
    for i in range(119, n):
        if d_arr[i] < split_date: continue
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
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); l2=v.get('ln_cap',22)
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        dt_str = str(d_arr[i])[:10]
        gtja_v = []
        for gn in GTJA_NAMES:
            sig = gtja_results.get(gn)
            if sig is not None and dt_str in sig.index and code in sig.columns:
                val = sig.loc[dt_str, code]
                gtja_v.append(float(val) if not np.isnan(val) else 0.0)
            else: gtja_v.append(0.0)
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,l2]+gtja_v+[rf], dtype=np.float32))
    cc += 1
    if cc%500==0 and len(rows)>0: print(f"  {cc}只 {len(rows):,}样本", flush=True)
    if len(rows) >= 100000: break  # 10万样本足够

arr=np.array(rows)
X=arr[:,:-1]; y=arr[:,-1]; y_cls=(y>0).astype(int)
for j in range(X.shape[1]):
    s=norm.get(f'feat_{j}',{})
    if s: X[:,j]=(np.clip(X[:,j],s['low'],s['high'])-s['mean'])/s['std']
X=np.nan_to_num(X, nan=0.0)

pred_reg = reg.predict(X)
raw_cls = cls.predict(X)  # raw margin scores for Booster
pred_cls = 1.0 / (1.0 + np.exp(-raw_cls))  # sigmoid to probability

auc_reg = roc_auc_score(y_cls, pred_reg)
auc_cls = roc_auc_score(y_cls, pred_cls)
acc_reg = ((pred_reg > 0) == y_cls).mean()
acc_cls = ((pred_cls > 0.5) == y_cls).mean()
reg_ic = stats.spearmanr(pred_reg, y)[0]

print(f"\n=== 验证结果 ({len(X):,} 样本) ===")
print(f"回归方向 AUC (reg_pred为分数):  {auc_reg:.4f}")
print(f"分类模型 AUC:                   {auc_cls:.4f}")
print(f"回归方向准确率 (pred>0):        {acc_reg:.2%}")
print(f"分类模型准确率 (prob>0.5):      {acc_cls:.2%}")
print(f"回归 IC:                         {reg_ic:.4f}")
print(f"正样本率:                        {y_cls.mean():.1%}")
