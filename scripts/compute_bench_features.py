"""阶段1：一次性计算70维特征+保存"""
import duckdb, numpy as np, pandas as pd, time, gzip, pickle
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT = Path('/tmp/bench_features.npz')

GTJA_39 = ['gtja_001','gtja_005','gtja_006','gtja_008','gtja_016','gtja_025','gtja_026',
    'gtja_032','gtja_034','gtja_035','gtja_038','gtja_041','gtja_042','gtja_046',
    'gtja_048','gtja_049','gtja_062','gtja_083','gtja_099','gtja_140','gtja_144',
    'gtja_145_inv','gtja_147_inv','gtja_150_inv','gtja_151_inv','gtja_156','gtja_157',
    'gtja_158_inv','gtja_159_inv','gtja_161_inv','gtja_167_inv','gtja_168','gtja_175_inv',
    'gtja_177','gtja_179_inv','gtja_184','gtja_185','gtja_187_inv','gtja_189_inv']

t0 = time.time()
print(f"[{time.strftime('%H:%M:%S')}] 1/4 加载GTJA...", flush=True)
with gzip.open(str(GTJA_PKL), 'rb') as f:
    gtja_raw = pickle.load(f)
print(f"    加载完成 ({time.time()-t0:.0f}s)", flush=True)

# 用 to_dict('index') 批量转换 — C层面完成，比Python循环快50x+
print(f"[{time.strftime('%H:%M:%S')}] 2/4 GTJA to_dict转换...", flush=True)
gtja_map = {}
for i, gn in enumerate(GTJA_39):
    gtja_map[gn] = gtja_raw[gn].to_dict('index')
    if (i+1) % 10 == 0:
        print(f"    [{i+1}/39] {gn} ({time.time()-t0:.0f}s)", flush=True)
del gtja_raw
print(f"    to_dict完成 ({time.time()-t0:.0f}s)", flush=True)

# DB数据
con = duckdb.connect(str(DB), read_only=True)
all_dates = sorted(str(r[0])[:10] for r in con.execute("SELECT DISTINCT date FROM stock_daily ORDER BY date").fetchall())
split_i = int(len(all_dates)*0.8)
test_dates = set(all_dates[split_i:])
print(f"测试期: {all_dates[split_i]} ~ {all_dates[-1]} ({len(test_dates)}天)", flush=True)

stocks = [r[0] for r in con.execute("""
    SELECT stock_code FROM (
        SELECT stock_code, SUM(amount) as amt FROM stock_daily
        WHERE date IN (SELECT date FROM stock_daily ORDER BY date DESC LIMIT 60)
        GROUP BY stock_code ORDER BY amt DESC LIMIT 2000
    )
""").fetchall()]
print(f"股票: {len(stocks)}只", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] 3/4 预取DB数据...", flush=True)
df = con.execute("""
    SELECT stock_code, date::VARCHAR as dt, close, high, low, change_pct/100.0 as ret, amount
    FROM stock_daily WHERE stock_code IN ({})
    ORDER BY stock_code, date
""".format(','.join(f"'{c}'" for c in stocks))).fetchdf()
val_df = con.execute("SELECT stock_code, date::VARCHAR as dt, pe_ttm, pb, total_mv FROM stock_valuation").fetchdf()
con.close()
print(f"  日线: {len(df):,}条, 估值: {len(val_df):,}条 ({time.time()-t0:.0f}s)", flush=True)

# 估值映射
val_map = {}
for _, r in val_df.iterrows():
    k = (r['stock_code'], r['dt'])
    ep = 1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else 0.5
    bp = 1.0/r['pb'] if r['pb'] and r['pb']>0 else 0.5
    lc = np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else 22.0
    val_map[k] = (ep, bp, lc)
del val_df

print(f"[{time.strftime('%H:%M:%S')}] 4/4 逐股票计算特征...", flush=True)
all_rows = []
n_ok = 0

for ci, (code, grp) in enumerate(df.groupby('stock_code', sort=False)):
    n = len(grp)
    if n < 120: continue
    c_arr = grp['close'].values.astype(np.float64)
    h_arr = grp['high'].values.astype(np.float64)
    l_arr = grp['low'].values.astype(np.float64)
    r_arr = grp['ret'].values.astype(np.float64)
    a_arr = grp['amount'].values.astype(np.float64)
    d_arr = grp['dt'].values
    n_ok += 1
    
    for i in range(119, n):
        ds = str(d_arr[i])[:10]
        if ds not in test_dates: continue
        
        lc = c_arr[i]
        
        chg5=lc/c_arr[i-5]-1; chg10=lc/c_arr[i-10]-1; chg20=lc/c_arr[i-20]-1
        chg60=lc/c_arr[i-60]-1; chg120=lc/c_arr[0]-1
        rng = slice(i-4,i+1); rng10 = slice(i-9,i+1); rng20 = slice(i-19,i+1); rng60 = slice(i-59,i+1)
        ma5=np.mean(c_arr[rng]); ma10=np.mean(c_arr[rng10]); ma20=np.mean(c_arr[rng20]); ma60=np.mean(c_arr[rng60])
        d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c_arr[:i+1])-1
        b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
        rn=np.max(c_arr[rng20])-np.min(c_arr[rng20]); rr=rn/np.min(c_arr[rng20])*100 if np.min(c_arr[rng20])>0 else 0
        std20=np.std(c_arr[rng20])/ma20*100 if ma20>0 else 0
        vols=a_arr[rng20]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c_arr[rng20]),np.max(c_arr[rng20]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r_arr[i] if i>0 else 0; c3d=lc/c_arr[i-3]-1 if c_arr[i-3]>0 else 0
        
        v = val_map.get((code, ds), (0.5, 0.5, 22.0))
        
        base23 = [chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                  b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d]+list(v)
        
        # 8个技术指标
        rsi=50; dif=0; macd_h=0; obv_z=0; bb_pct=0.5; bb_w=0; atr=0; corr_vp=0
        if i >= 14:
            chgs = r_arr[i-13:i+1]; g=np.maximum(chgs,0); l=np.maximum(-chgs,0)
            ag,al=np.mean(g),np.mean(l); rsi=100-100/(1+ag/al) if al>0 else 100
        if i >= 25:
            ema12=np.mean(c_arr[i-11:i+1]); ema26=np.mean(c_arr[i-25:i+1]); dif=ema12-ema26
            sig=np.mean([np.mean(c_arr[i-j-11:i-j+1])-np.mean(c_arr[i-j-25:i-j+1]) for j in range(9)])
            macd_h=dif-sig
        if i >= 20:
            obv=np.zeros(21)
            for j in range(1,21):
                if r_arr[i-20+j]>0: obv[j]=obv[j-1]+a_arr[i-20+j]
                elif r_arr[i-20+j]<0: obv[j]=obv[j-1]-a_arr[i-20+j]
                else: obv[j]=obv[j-1]
            obv_z=(obv[-1]-np.mean(obv))/np.std(obv) if np.std(obv)>0 else 0
        if i >= 19:
            bm=ma20; bs=np.std(c_arr[rng20]); bu=bm+2*bs; bl=bm-2*bs
            bb_pct=(lc-bl)/(bu-bl) if bu!=bl else 0.5; bb_w=(bu-bl)/bm if bm>0 else 0
        if i >= 14:
            trs=[max(c_arr[i-j]-c_arr[i-j-1],abs(c_arr[i-j]-h_arr[i-j]),abs(l_arr[i-j+1])) for j in range(1,15)]
            atr=np.mean(trs)/lc if lc>0 else 0
        if i >= 19:
            cv=np.corrcoef(r_arr[rng20],a_arr[rng20]); corr_vp=cv[0,1] if not np.isnan(cv[0,1]) else 0
        
        tech8 = [rsi/100,dif,macd_h,obv_z,bb_pct,bb_w,atr,corr_vp]
        
        # GTJA 39个：dict O(1)查找
        gtja_all = [gtja_map[gn].get(ds, {}).get(code, 0.0) for gn in GTJA_39]
        
        # 未来5日收益
        end = min(i+6, n)
        fwd = c_arr[i+1:end]
        rf = fwd[-1]/lc-1 if len(fwd)>=5 else (fwd[-1]/lc-1 if len(fwd)>=1 else 0)
        
        all_rows.append((ds, code, base23+tech8+gtja_all, rf))
    
    if ci % 200 == 199 or ci == len(stocks)-1:
        print(f"  [{n_ok}/{ci+1}] {len(all_rows):,} samples ({time.time()-t0:.0f}s)", flush=True)

stats = f"{len(all_rows):,}样本, {n_ok}只股票, {time.time()-t0:.0f}s"
print(f"特征完成: {stats}", flush=True)

# 保存
dates = np.array([r[0] for r in all_rows])
codes = np.array([r[1] for r in all_rows])
X = np.array([r[2] for r in all_rows], dtype=np.float32)
y = np.array([r[3] for r in all_rows], dtype=np.float32)
del all_rows

np.savez_compressed(OUT, X=X, y=y, dates=dates, codes=codes)
print(f"保存到 {OUT}: X {X.shape}, y {y.shape}", flush=True)
print(f"总耗时: {time.time()-t0:.0f}s", flush=True)
