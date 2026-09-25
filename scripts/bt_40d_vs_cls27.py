#!/usr/bin/env python3
"""快速对比：纯40d vs 40d×cls27方向确认"""
import os, json, gzip, pickle, time
import numpy as np
import duckdb
import lightgbm as lgb
from scipy import stats
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
MODEL_DIR = BASE / 'models'
t0 = time.time()

# 加载模型
reg40 = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_40d.txt'))
cls27 = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_cls_model.txt'))
print(f"reg40: {reg40.num_trees()}trees x {reg40.num_feature()}feat", flush=True)
print(f"cls27: {cls27.num_trees()}trees x {cls27.num_feature()}feat", flush=True)

with open(MODEL_DIR / 'v6_norm_stats_40d.json') as f: stats40 = json.load(f)

# GTJA
gtja_data = {}
gtja_pkl = BASE / 'gtja_signals.pkl.gz'
if gtja_pkl.exists():
    with gzip.open(str(gtja_pkl),'rb') as f: gtja_data = pickle.load(f)
GTJA_NAMES = ['gtja_006','gtja_083','gtja_177','gtja_184']

def get_gtja(code, dt_str):
    gtja_v = [0.0]*4
    for i,gn in enumerate(GTJA_NAMES):
        sig = gtja_data.get(gn)
        if sig is not None:
            for offset in range(6):
                sd = (datetime.strptime(dt_str[:10],'%Y-%m-%d')-timedelta(days=offset)).strftime('%Y-%m-%d')
                if sd in sig.index and code in sig.columns:
                    raw = sig.loc[sd,code]
                    if not np.isnan(raw): gtja_v[i]=float(raw); break
    return gtja_v

# Valuation
val_data = {}
val_rows = duckdb.connect(str(DB),read_only=True).execute(
    "SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date").fetchall()
for code,dt,pe,pb,mv in val_rows:
    ds=str(dt)[:10]; v={}
    if pe and pe>0: v['ep']=1.0/float(pe)
    if pb and pb>0: v['bp']=1.0/float(pb)
    if mv and mv>0: v['ln_cap']=np.log(float(mv))
    if v: val_data[(code,ds)]=v

con = duckdb.connect(str(DB), read_only=True)
all_dates = [str(r[0])[:10] for r in con.execute("SELECT DISTINCT date FROM stock_daily ORDER BY date").fetchall()]
idx_data = con.execute("SELECT date,close FROM index_daily WHERE index_code='000001' ORDER BY date").fetchall()
idx_dates=[str(r[0])[:10] for r in idx_data]; idx_closes=np.array([float(r[1]) for r in idx_data])

years = [
    ('2020','2020-01-01','2020-12-31'),
    ('2021','2021-01-01','2021-12-31'),
    ('2022','2022-01-01','2022-12-31'),
    ('2023','2023-01-01','2023-12-31'),
    ('2024','2024-01-01','2024-12-31'),
    ('2025','2025-01-01','2025-12-31'),
    ('2026','2026-01-01','2026-06-05'),
]

stocks = [r[0] for r in con.execute(
    "SELECT stock_code FROM stock_daily GROUP BY stock_code HAVING COUNT(*)>=160 ORDER BY stock_code").fetchall()]

def compute_feats(c_arr, dt_str, code):
    c = np.array(c_arr[-120:], dtype=np.float64); lc=c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1; chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100; vr=1.0
    rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0; c1d=0.0; c3d=lc/c[-3]-1 if len(c)>=3 else 0
    v=val_data.get((code,dt_str),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22.0)
    idx_pos=idx_dates.index(dt_str) if dt_str in idx_dates else -1
    if idx_pos>=20:
        ex5=chg5-(idx_closes[idx_pos]/idx_closes[idx_pos-5]-1)
        ex10=chg10-(idx_closes[idx_pos]/idx_closes[idx_pos-10]-1)
        ex20=chg20-(idx_closes[idx_pos]/idx_closes[idx_pos-20]-1)
    else: ex5=ex10=ex20=0.0
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap,ex5,ex10,ex20], dtype=np.float64)

def compute_cls27_feats(c_arr, dt_str, code):
    """27 features for cls27: 20 base + ep/bp/ln_cap + 4 GTJA"""
    c = np.array(c_arr[-120:], dtype=np.float64); lc=c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1; chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100; vr=1.0
    rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0; c1d=0.0; c3d=lc/c[-3]-1 if len(c)>=3 else 0
    v=val_data.get((code,dt_str),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22.0)
    gtja = get_gtja(code, dt_str)
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap]+gtja, dtype=np.float64)

def standardize(f, stats_obj, n=23):
    f = f.copy()
    for j in range(min(n, len(f))):
        key = f'feat_{j}'
        if key in stats_obj:
            s = stats_obj[key]
            if s['std'] > 0:
                f[j] = max(f[j], s['low'])
                f[j] = min(f[j], s['high'])
                f[j] = (f[j] - s['mean']) / s['std']
    return f

def run_backtest(start, end):
    bt_dates = [d for d in all_dates if start<=d<=end]
    bt_set = set(bt_dates)
    
    # Pre-load top300 for each date
    date_top300 = {}
    for dt in bt_dates:
        rows = con.execute(f"SELECT stock_code,amount FROM stock_daily WHERE date='{dt}' ORDER BY amount DESC LIMIT 300").fetchall()
        date_top300[dt] = {r[0]:float(r[1] or 0) for r in rows}
    
    results = {'pure40': {}, 'cls40_cls': {}, 'cls40_cont': {}}
    fwd_ret = {}
    
    for code in stocks:
        rows = con.execute(f"SELECT date,close,COALESCE(change_pct,0),amount FROM stock_daily WHERE stock_code='{code}' ORDER BY date").fetchall()
        n = len(rows)
        if n < 160: continue
        dates = [str(r[0])[:10] for r in rows]
        closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        for i in range(119, n-20):
            dt = dates[i]
            if dt not in bt_set: continue
            if code not in date_top300.get(dt,{}): continue
            
            cw = closes[:i+1]
            fwd = closes[i+20]/closes[i]-1 if i+20<n else None
            
            gtja_v = get_gtja(code, dt)
            
            # 40d
            raw40 = compute_feats(cw, dt, code)
            f40 = standardize(raw40[:23].copy(), stats40, 23)
            f40 = np.append(f40, np.array(gtja_v, dtype=np.float64))
            f40 = np.nan_to_num(f40.reshape(1,-1), nan=0.0)
            p40 = float(reg40.predict(f40)[0])
            s40 = min(100, max(0, (p40+10)/50*100))
            
            # cls27
            f27 = compute_cls27_feats(cw, dt, code)
            f27 = np.nan_to_num(f27.reshape(1,-1), nan=0.0, posinf=0.0, neginf=0.0)
            cls_p = float(cls27.predict(f27)[0])
            
            # Pure 40d score
            results['pure40'].setdefault(dt,{})[code] = s40
            
            # Binary filter: only if cls prob >= 0.55
            s40_cls = s40 if cls_p >= 0.55 else 0
            results['cls40_cls'].setdefault(dt,{})[code] = s40_cls
            
            # Continuous: s40 * (cls_prob / 0.5)
            s40_cont = s40 * (cls_p / 0.5)
            results['cls40_cont'].setdefault(dt,{})[code] = s40_cont
            
            if dt not in fwd_ret: fwd_ret[dt] = {}
            fwd_ret[dt][code] = fwd
    
    return results, fwd_ret

def evaluate(preds, fwd_ret):
    dates = sorted(preds.keys())
    top_hits = []; rank_ics = []; decile_spreads = []
    
    for dt in dates:
        pairs = [(preds[dt][c], fwd_ret[dt][c]) for c in preds[dt] if fwd_ret[dt][c] is not None]
        if len(pairs) < 30: continue
        
        scores = np.array([p[0] for p in pairs])
        fwd_values = np.array([p[1] for p in pairs])
        
        # Rank IC
        if len(set(scores))>1 and len(set(fwd_values))>1:
            rank_ics.append(float(stats.spearmanr(scores, fwd_values)[0]))
        
        # Top10% vs Bottom10%
        sort_idx = np.argsort(scores)
        n_g = len(sort_idx)//10
        bot = fwd_values[sort_idx[:n_g]].mean()
        top = fwd_values[sort_idx[-n_g:]].mean()
        decile_spreads.append(top-bot)
        
        # Top10% hit rate
        top_ret = fwd_values[sort_idx[-n_g:]]
        all_ret = fwd_values
        top_hits.append((np.mean(top_ret>0)*100, np.mean(all_ret>0)*100))
    
    return top_hits, rank_ics, decile_spreads

print(f"\n{'年份':>6s} {'方法':>10s} {'IC':>7s} {'Top命中':>7s} {'市场':>7s} {'多空差':>7s} {'天数':>5s}")
print('-' * 55)

for ylabel, start, end in years:
    preds, fwd = run_backtest(start, end)
    
    for mk, label in [('pure40','纯40d'),('cls40_cls','cls27过滤'),('cls40_cont','cls27连续')]:
        top_hits, rank_ics, spreads = evaluate(preds[mk], fwd)
        if not top_hits: continue
        th = np.mean([t[0] for t in top_hits])
        mh = np.mean([t[1] for t in top_hits])
        ric = np.mean(rank_ics) if rank_ics else 0
        sp = np.mean(spreads) if spreads else 0
        nd = len(rank_ics)
        print(f"{ylabel:>6s} {label:>10s} {ric:>6.3f} {th:>6.1f}% {mh:>6.1f}% {sp*100:>6.2f}% {nd:>5d}")
    print()

con.close()
print(f"Total: {time.time()-t0:.0f}s", flush=True)
