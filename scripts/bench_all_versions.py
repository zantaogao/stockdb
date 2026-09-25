"""统一基准测试 — v1~v5对比（高效版，一次运算）"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, gzip, pickle, sys
from scipy import stats
from sklearn.metrics import roc_auc_score
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
MD = BASE / 'models'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
LOG = Path('/tmp/bench_run.log')

def log(msg):
    with open(LOG, 'a') as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    print(msg, flush=True)

GTJA_39 = ['gtja_001','gtja_005','gtja_006','gtja_008','gtja_016','gtja_025','gtja_026',
    'gtja_032','gtja_034','gtja_035','gtja_038','gtja_041','gtja_042','gtja_046',
    'gtja_048','gtja_049','gtja_062','gtja_083','gtja_099','gtja_140','gtja_144',
    'gtja_145_inv','gtja_147_inv','gtja_150_inv','gtja_151_inv','gtja_156','gtja_157',
    'gtja_158_inv','gtja_159_inv','gtja_161_inv','gtja_167_inv','gtja_168','gtja_175_inv',
    'gtja_177','gtja_179_inv','gtja_184','gtja_185','gtja_187_inv','gtja_189_inv']
GTJA_4 = ['gtja_006','gtja_184','gtja_177','gtja_083']

# 加载GTJA
log("加载GTJA...")
t0 = time.time()
with gzip.open(str(GTJA_PKL), 'rb') as f:
    gtja_raw = pickle.load(f)
log(f"  GTJA原始数据加载: {list(gtja_raw.keys())[:3]}... ({time.time()-t0:.0f}s)")

# 预计算GTJA为date→code→value dict加速查询
gtja_map = {}
for gn in GTJA_39:
    df = gtja_raw[gn]
    d = {}
    for dt in df.index:
        row = df.loc[dt]
        d[str(dt)[:10]] = {code: float(row[code]) for code in row.index if not np.isnan(row[code])}
    gtja_map[gn] = d
log(f"  GTJA dicts构建完成 ({time.time()-t0:.0f}s)")

del gtja_raw

# 加载模型
models = {}
for ver, regf, clsf in [
    ('v1','lgb_reg_final.txt','lgb_cls_final.txt'),
    ('v2','lgb_reg_v2.txt','lgb_cls_v2.txt'),
    ('v3','lgb_reg_v3.txt','lgb_cls_v3.txt'),
    ('v4','lgb_reg_v4.txt','lgb_cls_v4.txt'),
    ('v5','lgb_reg_v5.txt','lgb_cls_v5.txt'),
]:
    rp, cp = MD/regf, MD/clsf
    if rp.exists() and cp.exists():
        m = lgb.Booster(model_file=str(rp))
        c = lgb.Booster(model_file=str(cp))
        models[ver] = (m, c)
        log(f"  {ver}: {rp.name} ({m.num_feature()}维)")

con = duckdb.connect(str(DB), read_only=True)

# 测试集：最近20%交易日
all_dates = sorted(str(r[0])[:10] for r in con.execute("SELECT DISTINCT date FROM stock_daily ORDER BY date").fetchall())
split_i = int(len(all_dates)*0.8)
test_dates = set(all_dates[split_i:])
log(f"测试期: {all_dates[split_i]} ~ {all_dates[-1]} ({len(test_dates)}天)")

# 成交额TOP 2000
stocks = [r[0] for r in con.execute("""
    SELECT stock_code FROM (
        SELECT stock_code, SUM(amount) as amt FROM stock_daily
        WHERE date IN (SELECT date FROM stock_daily ORDER BY date DESC LIMIT 60)
        GROUP BY stock_code ORDER BY amt DESC LIMIT 2000
    )
""").fetchall()]
log(f"股票: {len(stocks)}只")

# 预取全部数据
log("预取数据...")
t1 = time.time()
df = con.execute("""
    SELECT stock_code, date::VARCHAR as dt, close, high, low, change_pct/100.0 as ret, amount
    FROM stock_daily WHERE stock_code IN ({})
    ORDER BY stock_code, date
""".format(','.join(f"'{c}'" for c in stocks))).fetchdf()
val_df = con.execute("SELECT stock_code, date::VARCHAR as dt, pe_ttm, pb, total_mv FROM stock_valuation").fetchdf()
con.close()
log(f"  日线: {len(df):,}条, 估值: {len(val_df):,}条 ({time.time()-t1:.0f}s)")

# 估值映射
val_map = {}
for _, r in val_df.iterrows():
    k = (r['stock_code'], r['dt'])
    ep = 1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp = 1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc = np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]):
        val_map[k] = {'ep':ep or 0.5,'bp':bp or 0.5,'ln_cap':lc or 22.0}
del val_df

# ── 逐股票计算特征 ──
log("特征计算（逐股票循环）...")
all_rows = []

for ci, (code, grp) in enumerate(df.groupby('stock_code', sort=False)):
    n = len(grp)
    if n < 120: continue
    c_arr = grp['close'].values.astype(np.float64)
    h_arr = grp['high'].values.astype(np.float64)
    l_arr = grp['low'].values.astype(np.float64)
    r_arr = grp['ret'].values.astype(np.float64)
    a_arr = grp['amount'].values.astype(np.float64)
    d_arr = grp['dt'].values
    
    for i in range(119, n):
        ds = str(d_arr[i])[:10]
        if ds not in test_dates: continue
        
        c = c_arr[:i+1]; lc = c[-1]
        hi20 = h_arr[i-19:i+1]; lo20 = l_arr[i-19:i+1]
        
        chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1; chg60=lc/c[-60]-1; chg120=lc/c[0]-1
        ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
        d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
        b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
        rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
        std20=np.std(c[-20:])/np.mean(c[-20:])*100
        vols=a_arr[i-19:i+1]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r_arr[i] if i>0 else 0; c3d=lc/c[-3]-1 if len(c)>=3 and c[-3]>0 else 0
        
        v = val_map.get((code, ds), {})
        ep = v.get('ep',0.5); bp = v.get('bp',0.5); lc2 = v.get('ln_cap',22.0)
        
        base23 = [chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                  b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,lc2]
        
        # 8个技术指标
        n_i = len(c)
        rsi=50; dif=0; macd_h=0; obv_z=0; bb_pct=0.5; bb_w=0; atr=0; corr_vp=0
        if n_i >= 15:
            chgs = r_arr[i-13:i+1]; g=np.maximum(chgs,0); l=np.maximum(-chgs,0)
            ag,al=np.mean(g),np.mean(l); rsi=100-100/(1+ag/al) if al>0 else 100
        if n_i >= 26:
            ema12=np.mean(c[-12:]); ema26=np.mean(c[-26:]); dif=ema12-ema26
            sig=np.mean([np.mean(c[-j-12:-j])-np.mean(c[-j-26:-j]) for j in range(min(9,i-25))])
            macd_h=dif-sig
        if n_i >= 21:
            obv=np.zeros(21)
            for j in range(1,21):
                if r_arr[i-20+j]>0: obv[j]=obv[j-1]+a_arr[i-20+j]
                elif r_arr[i-20+j]<0: obv[j]=obv[j-1]-a_arr[i-20+j]
                else: obv[j]=obv[j-1]
            obv_z=(obv[-1]-np.mean(obv))/np.std(obv) if np.std(obv)>0 else 0
        if n_i >= 20:
            bm=np.mean(c[-20:]); bs=np.std(c[-20:]); bu=bm+2*bs; bl=bm-2*bs
            bb_pct=(lc-bl)/(bu-bl) if bu!=bl else 0.5; bb_w=(bu-bl)/bm if bm>0 else 0
        if n_i >= 15:
            trs=[max(c[-j]-c[-j-1],abs(c[-j]-h_arr[i-j]),abs(l_arr[i-j+1])) for j in range(1,15)]
            atr=np.mean(trs)/lc if lc>0 else 0
        if n_i >= 20:
            cv=np.corrcoef(r_arr[i-19:i+1],a_arr[i-19:i+1]); corr_vp=cv[0,1] if not np.isnan(cv[0,1]) else 0
        
        tech8 = [rsi/100,dif,macd_h,obv_z,bb_pct,bb_w,atr,corr_vp]
        
        # GTJA 39个
        gtja_all = []
        for gn in GTJA_39:
            d = gtja_map[gn].get(ds, {})
            gtja_all.append(d.get(code, 0.0))
        
        # 未来5日收益
        end = min(i+6, n)
        fwd = c_arr[i+1:end]
        rf = fwd[-1]/lc-1 if len(fwd)>=5 else (fwd[-1]/lc-1 if len(fwd)>=1 else 0)
        
        all_rows.append((ds, code, base23+tech8+gtja_all, rf))
    
    if ci % 100 == 99:
        log(f"  [{ci+1}/{len(stocks)}] stocks, {len(all_rows):,} samples so far ({time.time()-t0:.0f}s)")

log(f"特征完成: {len(all_rows):,}样本 ({time.time()-t0:.0f}s)")

# ── 各版本预测 ──
X_70 = np.nan_to_num(np.array([r[2] for r in all_rows]), nan=0.0)
y_all = np.array([r[3] for r in all_rows])
codes = np.array([r[1] for r in all_rows])
dates_obj = np.array([r[0] for r in all_rows])

# z-score标准化前23维
for j in range(23):
    col = X_70[:,j]
    l,h = np.percentile(col[~np.isnan(col)],[1,99])
    col = np.clip(col,l,h); m,s = np.nanmean(col),np.nanstd(col)
    if s>0: X_70[:,j] = (col-m)/s

del all_rows

log(f"\n{'='*75}")
log(f"{'版本':>4} {'维数':>4} {'回归IC':>8} {'分类AUC':>8} {'多空差':>7} {'TOP10%胜率':>10} {'TOP10胜率':>10} {'样本':>8}")
log("-"*75)

results = {}
for ver in ['v1','v2','v3','v4','v5']:
    if ver not in models: continue
    reg_m, cls_m = models[ver]
    nf = reg_m.num_feature()
    
    idx = None
    if ver == 'v1': idx = list(range(20))
    elif ver == 'v2': idx = list(range(23))
    elif ver == 'v3':
        idx = list(range(20)) + list(range(23,31))  # 20base + 8tech + 3val = 31
    elif ver == 'v4': idx = list(range(23)) + list(range(31, 70))  # 23base+39gtja=62
    elif ver == 'v5': idx = list(range(23)) + [31, 34, 35, 36]  # gtja_006=0,184=3,177=4,083=5 in GTJA_39
    
    if idx is None or len(idx) != nf:
        log(f"{ver:>4} {nf:>4}  × 特征不匹配({len(idx)} vs {nf})")
        continue
    
    X_v = X_70[:, idx]
    
    pred_reg = reg_m.predict(X_v)
    pred_cls = cls_m.predict(X_v)
    
    reg_ic = stats.spearmanr(pred_reg, y_all)[0]
    y_bin = (y_all > 0).astype(int)
    cls_auc = roc_auc_score(y_bin, pred_cls) if len(set(y_bin))>1 else 0
    
    df = pd.DataFrame({'date':dates_obj,'code':codes,'pred':pred_reg,'ret':y_all})
    df = df.dropna(subset=['ret']).copy()
    
    spreads = []
    top10p_rates = []
    for dt, g in df.groupby('date'):
        if len(g) < 20: continue
        g = g.sort_values('pred', ascending=False)
        n10 = max(len(g)//10, 5)
        top = g.iloc[:n10]
        bot = g.iloc[-n10:]
        spreads.append(top['ret'].mean() - bot['ret'].mean())
        top10p_rates.append((top['ret'] > 0).mean())
    
    spread = np.mean(spreads) if spreads else 0
    top10p_win = np.mean(top10p_rates) if top10p_rates else 0
    
    # TOP10 only
    top10_win_by_day = []
    for dt, g in df.groupby('date'):
        if len(g) < 10: continue
        top10 = g.sort_values('pred', ascending=False).iloc[:10]
        top10_win_by_day.append((top10['ret'] > 0).mean())
    top10_win = np.mean(top10_win_by_day) if top10_win_by_day else 0
    
    results[ver] = (reg_ic, cls_auc, spread, top10p_win, top10_win, len(df))
    
    tag = ' 🏆' if ver == 'v5' else ''
    log(f"{ver:>4} {nf:>4}  {reg_ic:>+7.4f}  {cls_auc:>7.4f}  {spread*100:>+5.2f}%  {top10p_win:>8.1%}  {top10_win:>8.1%}  {len(df):>7,}{tag}")

log("="*75)
log(f"总耗时: {time.time()-t0:.0f}s")
