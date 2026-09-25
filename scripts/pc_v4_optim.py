"""
v4 综合优化
A: 融合权重重调 (reg/cls v4 62-dim + LSTM保持35%)
B: GTJA前向选择 (边际IC验证)
C: 分类阈值 (夏普最大化)

注意: 不含emoji (Windows GBK兼容)
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, pickle, gzip
from scipy import stats
import warnings; warnings.filterwarnings('ignore')

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
t0 = time.time()
LOG = []

def log_msg(m):
    print(m, flush=True); LOG.append(m)

log_msg("="*60)
log_msg("V4 综合优化")

# ── 1. 加载 ──
log_msg("\n[1] 加载模型+GTJA因子...")
reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v4.txt")
cls = lgb.Booster(model_file=f"{OUT}/lgb_cls_v4.txt")
assert reg.num_feature() == 62
assert cls.num_feature() == 62

with gzip.open(f"{OUT}/gtja_signals.pkl.gz", 'rb') as f:
    gtja_results = pickle.load(f)
gtja_names = list(gtja_results.keys())
log_msg(f"  reg={reg.num_trees()}trees cls={cls.num_trees()}trees GTJA={len(gtja_names)}factors")

# ── 2. 特征生成 ──
log_msg("\n[2] 特征生成...")
con = duckdb.connect(DB)
daily = con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, amount
    FROM stock_daily WHERE date >= '2024-01-01' ORDER BY stock_code, date
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

rows, meta = [], []
for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=grp['close'].values.astype(np.float64)
    r_arr=grp['ret'].values.astype(np.float64); a_arr=grp['amount'].values.astype(np.float64)
    d_arr=grp['date'].values
    if n<120: continue
    for i in range(119,n):
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
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); lc2=v.get('ln_cap',22)
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        
        dt_str = str(d_arr[i])[:10]
        gtja_v = []
        for gn in gtja_names:
            sig = gtja_results[gn]
            if dt_str in sig.index and code in sig.columns:
                val = sig.loc[dt_str, code]
                gtja_v.append(float(val) if not np.isnan(val) else 0.0)
            else:
                gtja_v.append(0.0)
        
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,lc2]+gtja_v, dtype=np.float32))
        meta.append({'date':dt_str,'code':code,'rf':rf})

X = np.nan_to_num(np.array(rows), nan=0.0)
log_msg(f"  样本: {len(X):,} x {X.shape[1]}维")

# ── 3. 标准化+预测 ──
log_msg("\n[3] 模型预测...")
split80 = int(len(X)*0.8)
for j in range(23):
    col=X[:split80,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99])
    col=np.clip(col,l,h); m,s=np.nanmean(col),np.nanstd(col)
    if s>0: X[:,j]=(np.clip(X[:,j],l,h)-m)/s

pred_reg = reg.predict(X, num_threads=4)
pred_cls = cls.predict(X, num_threads=4)

df = pd.DataFrame(meta)
df['reg'] = pred_reg; df['cls'] = pred_cls
df['rf'] = df['rf'].astype(float)
dates = sorted(df['date'].unique())
log_msg(f"  完成: {len(df)}条 {len(dates)}天")
log_msg(f"  reg IC(全局): {stats.spearmanr(pred_reg,df['rf'])[0]:.4f}")
log_msg(f"  cls IC(全局): {stats.spearmanr(pred_cls,df['rf'])[0]:.4f}")

# ── A. 融合权重枚举 ──
log_msg("\n" + "="*60)
log_msg("A. 融合权重枚举 (reg+cls v4, LSTM保持35%, rules=10)")
log_msg("   搜索 reg/cls/LSTM/rules 组合, LSTM暂用rf替代(上限基准)")

for c in ['reg','cls']:
    df[f'{c}_n'] = df.groupby('date')[c].transform(
        lambda g: (g-g.min())/(g.max()-g.min()+1e-10)*100)

w_results = []
for wr in range(10, 51, 5):
    for wc in range(5, 41, 5):
        wl = 35; wru = 10
        rem = 100 - wr - wc - wl - wru
        if abs(rem) > 5: continue
        wca = max(0, wc + rem)
        if wca > 45: continue
        
        # LSTM=35固定, 只调reg/cls比例
        df['comp'] = (df['reg_n']*wr + df['cls_n']*wca + df['rf']*wl + 50*wru)/100
        val_dates = df['date'].iloc[split80:].unique()
        dret = df[df['date'].isin(val_dates)].groupby('date').apply(
            lambda g: g.sort_values('comp',ascending=False)
            .iloc[:max(len(g)//10,5)]['rf'].mean()
            - g.sort_values('comp',ascending=False)
            .iloc[-max(len(g)//10,5):]['rf'].mean())
        w_results.append({
            'reg':wr,'cls':wca,'lstm':wl,'rules':wru,
            'spread':dret.mean()*100,
            'sharpe':dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0,
            'win_rate':(dret>0).mean()*100})

w_df = pd.DataFrame(w_results).sort_values('spread',ascending=False)
log_msg(f"{'reg/cls/lstm/rules':^30} {'spread%':^8} sharpe  win%")
log_msg("-"*55)
for _,r in w_df.head(8).iterrows():
    log_msg(f"  {r['reg']:3.0f}/{r['cls']:3.0f}/{r['lstm']:3.0f}/{r['rules']:3.0f}  {r['spread']:>+6.2f}%  {r['sharpe']:>5.2f}  {r['win_rate']:4.0f}%")
cur = w_df[(w_df.reg==25)&(w_df.cls==30)]
if len(cur)>0:
    log_msg(f"\n当前(25/30/35/10): spread={cur.iloc[0]['spread']:+.2f}%  sharpe={cur.iloc[0]['sharpe']:.2f}")

# ── B. GTJA前向选择 ──
log_msg("\n" + "="*60)
log_msg("B. GTJA前向选择")

X_tr = X[:split80]; y_tr = df['rf'].values[:split80]
X_te = X[split80:]; y_te = df['rf'].values[split80:]

base = lgb.LGBMRegressor(n_estimators=200, max_depth=6, num_leaves=31,
    learning_rate=0.1, random_state=42, n_jobs=4, verbose=-1)
base.fit(X_tr[:,:23], y_tr)
base_ic = stats.spearmanr(base.predict(X_te[:,:23]), y_te)[0]
log_msg(f"基础模型(23维): IC={base_ic:.4f}")

# 预计算各GTJA单因子IC
gtja_ics = []
for i,gn in enumerate(gtja_names):
    col = X_te[:,23+i]
    valid = ~np.isnan(col)
    if valid.sum() > 100:
        ic = abs(stats.spearmanr(col[valid], y_te[valid])[0])
    else: ic = 0
    gtja_ics.append((gn, ic, i))
gtja_ranked = sorted(gtja_ics, key=lambda x: -x[1])

log_msg("GTJA |IC| TOP10:")
for gn,ic,_ in gtja_ranked[:10]:
    log_msg(f"  {gn}: {ic:.4f}")

# 前向选择
selected = []; best_ic = base_ic; cols = list(range(23))
for step in range(min(30, len(gtja_names))):
    best_gain, best_gn, best_idx = -1, None, None
    for gn, _, idx in gtja_ranked:
        if gn in selected: continue
        ci = 23 + idx
        m = lgb.LGBMRegressor(n_estimators=200, max_depth=6, num_leaves=31,
            learning_rate=0.1, random_state=42, n_jobs=4, verbose=-1)
        m.fit(X_tr[:,cols+[ci]], y_tr)
        ic = stats.spearmanr(m.predict(X_te[:,cols+[ci]]), y_te)[0]
        gain = ic - best_ic
        if gain > best_gain: best_gain=gain; best_gn=gn; best_idx=ci
    if best_gain >= 0.001:  # 宽松一点
        selected.append(best_gn); cols.append(best_idx); best_ic += best_gain
        log_msg(f"  +{best_gn}: IC={best_ic:.4f} (gain=+{best_gain:.4f})")
    else:
        log_msg(f"  停止: max_gain={best_gain:.4f}")
        break

log_msg(f"\n最终: 基础+{len(selected)}={len(cols)}维, IC={best_ic:.4f}")
if selected: log_msg(f"选中: {selected}")

# ── C. 分类阈值 ──
log_msg("\n" + "="*60)
log_msg("C. 分类阈值优化")

y_bin = (y_tr > 0).astype(int)
y_prob = cls.predict(X_tr, num_threads=4)

th_results = []
for th in np.arange(0.1, 0.91, 0.02):
    sig = (y_prob >= th).astype(int)
    tp=((sig==1)&(y_bin==1)).sum(); fp=((sig==1)&(y_bin==0)).sum()
    tn=((sig==0)&(y_bin==0)).sum(); fn=((sig==0)&(y_bin==1)).sum()
    prec=tp/(tp+fp) if (tp+fp)>0 else 0
    rec=tp/(tp+fn) if (tp+fn)>0 else 0
    f1=2*prec*rec/(prec+rec) if (prec+rec)>0 else 0
    # 交易夏普: 信号日收益率序列
    tr = []; n_b = len(y_prob)//63
    for b in range(n_b):
        s = y_prob[b*63:(b+1)*63] >= th
        if s.sum()>0:
            tr.append(y_tr[b*63:(b+1)*63][s].mean())
    sr = np.mean(tr)/np.std(tr)*np.sqrt(252) if tr and np.std(tr)>0 else 0
    th_results.append({'thresh':th,'prec':prec,'rec':rec,'f1':f1,'acc':(tp+tn)/(tp+fp+tn+fn),'sharpe':sr})

tr_df = pd.DataFrame(th_results)
best = tr_df.loc[tr_df['sharpe'].idxmax()]
log_msg(f"最优: thresh={best['thresh']:.2f} sharpe={best['sharpe']:.2f} prec={best['prec']:.3f} rec={best['rec']:.3f} f1={best['f1']:.3f}")
cur = tr_df[tr_df.thresh==0.5]
if len(cur)>0:
    log_msg(f"当前0.50: sharpe={cur.iloc[0]['sharpe']:.2f} f1={cur.iloc[0]['f1']:.3f}")

log_msg("\n" + "="*60)
log_msg(f"总耗时: {time.time()-t0:.0f}s")

# 保存
w_df.to_csv(f"{OUT}/weight_bt_v4.csv", index=False)
tr_df.to_csv(f"{OUT}/cls_thresh_v4.csv", index=False)
open(f"{OUT}/v4_optim_results.txt",'w',encoding='utf-8').write('\n'.join(LOG))
log_msg(f"结果已保存")
