"""
快速权重验证 — v6测试集
比较: reg-only, reg+rules, reg+lstm+rules
"""
import duckdb, json, numpy as np, pandas as pd, lightgbm as lgb, time
from scipy import stats
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

# 加载数据（复用v6逻辑，只取最后20%作测试集）
con = duckdb.connect(DB)
daily = con.execute("""
    SELECT stock_code, date, open, close, high, low,
           change_pct/100.0 as ret, amount, volume
    FROM stock_daily WHERE date >= '2019-06-01' ORDER BY stock_code, date
""").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
# 规则分所需数据（基本面因子）
fin = con.execute("""
    SELECT stock_code, report_date as date, 
           CAST(roe AS DOUBLE)/100 as roe,
           CAST(net_margin AS DOUBLE)/100 as net_margin
    FROM fin_income WHERE report_date >= '2020-01-01' ORDER BY stock_code, report_date
""").fetchdf()
con.close()

vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

# 规则分: ROE排名 + net_margin排名 + 估值排名 (0-100)
rule_scores = {}
for code, grp in fin.groupby('stock_code'):
    last = grp.iloc[-1] if len(grp) > 0 else None
    if last is not None and last['roe'] and not np.isnan(last['roe']):
        rule_scores[code] = last['roe'] * 50 + (last['net_margin'] or 0) * 30

# GTJA panel + 因子
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

# 加载模型和标准化统计量
reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v6.txt")
norm = json.load(open(f"{OUT}/v6_norm_stats.json"))

# 特征生成（只取测试集）
all_dates = sorted(daily['date'].unique())
split_idx = int(len(all_dates) * 0.8)
split_date = all_dates[split_idx]

rows = []; cc = 0
for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=np.nan_to_num(grp['close'].values.astype(np.float64))
    r_arr=np.nan_to_num(grp['ret'].values.astype(np.float64))
    a_arr=np.nan_to_num(grp['amount'].values.astype(np.float64))
    d_arr=grp['date'].values
    rul = rule_scores.get(code, 50)
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
            b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,l2]+gtja_v+[rf, rul], dtype=np.float32))
    cc += 1
    if cc%500==0 and len(rows)>0: print(f"  {cc}只 {len(rows):,}样本", flush=True)
    if len(rows) >= 100000: break

arr=np.array(rows)
print(f"arr shape: {arr.shape}", flush=True)
# 27 features + rf + rule = 29 cols
X=arr[:,:27]; y=arr[:,27]; rule_raw=arr[:,28]
X=np.nan_to_num(X, nan=0.0)
for j in range(27):
    s=norm.get(f'feat_{j}',{})
    if s and s['std']>0: X[:,j]=(np.clip(X[:,j],s['low'],s['high'])-s['mean'])/s['std']
X=np.nan_to_num(X, nan=0.0)

pred_reg = reg.predict(X)
y_cls = (y > 0).astype(int)

# 归一化规则分到0-100
rule_min, rule_max = np.percentile(rule_raw, [1, 99])
rule_score = np.clip((rule_raw - rule_min) / (rule_max - rule_min) * 100, 0, 100)
rule_score = np.nan_to_num(rule_score, nan=50)

# 回归分映射到0-100
reg_score = np.clip((pred_reg * 100 + 10) / 40 * 100, 0, 100)

# 测试各权重组合
combos = [
    ('reg 50% + rules 50%', 0.5, 0.0, 0.5),
    ('reg 60% + rules 40%', 0.6, 0.0, 0.4),
    ('reg 70% + rules 30%', 0.7, 0.0, 0.3),
    ('reg 80% + rules 20%', 0.8, 0.0, 0.2),
    ('reg 90% + rules 10%', 0.9, 0.0, 0.1),
    ('reg 55% + rules 45%', 0.55, 0.0, 0.45),  # 方案B
    ('reg 40% + rules 60%', 0.40, 0.0, 0.60),  # 方案C
]

print(f"\n{'='*60}")
print(f"权重对比 ({len(X):,} 样本)")
print(f"{'='*60}")
print(f"{'方案':20s} {'IC':>8s} {'AUC(dir)':>10s} {'Spread':>8s}")
print(f"{'-'*46}")

for name, wr, wl, wru in combos:
    if wl == 0:
        comp = reg_score * wr + rule_score * wru
    else:
        comp = reg_score * wr + rule_score * wru
    
    ic = stats.spearmanr(comp, y)[0] if np.std(comp) > 0 else 0
    auc = stats.spearmanr(comp, y_cls)[0] if np.std(comp) > 0 else 0
    
    # 分位数组
    df = pd.DataFrame({'comp': comp, 'ret': y})
    df['decile'] = pd.qcut(df['comp'].rank(), 10, labels=False, duplicates='drop')
    grp = df.groupby('decile')['ret'].mean()
    spread = grp.iloc[-1] - grp.iloc[0] if len(grp) > 1 else 0
    
    print(f"{name:20s} {ic:>8.4f} {auc:>10.4f} {spread*100:>7.2f}%")

print(f"{'='*60}")
print(f"耗时: {time.time()-t0:.0f}s", flush=True)
