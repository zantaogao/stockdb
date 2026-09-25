#!/usr/bin/env python3
"""
权重优化枚举 — 基于历史回测数据
1. 重放历史（同 backtest_historical.py）
2. 枚举所有权重组合 → 找最优IC和分组收益
"""
import os, sys, json, gzip, pickle, time
import numpy as np
import duckdb
import lightgbm as lgb
from scipy import stats
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
MODEL_DIR = BASE / 'models'
OUTPUT = BASE / 'backtest_results'
OUTPUT.mkdir(exist_ok=True)

START_DATE = '2020-01-01'
END_DATE = '2026-06-05'
t0 = time.time()

print("=" * 70)
print("权重优化枚举 — 历史回测")
print("=" * 70)

# ═══ 1. 加载模型 ═══
print("\n[1/5] 加载模型...")
reg20 = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_model.txt'))
reg10 = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_10d.txt'))
reg40 = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_40d.txt'))
print(f"  20d: {reg20.num_trees()}trees  10d: {reg10.num_trees()}trees  40d: {reg40.num_trees()}trees")

with open(MODEL_DIR / 'v6_norm_stats.json') as f: stats20 = json.load(f)
with open(MODEL_DIR / 'v10_norm_stats.json') as f: stats10 = json.load(f)
with open(MODEL_DIR / 'v6_norm_stats_40d.json') as f: stats40 = json.load(f)

gtja_data = {}
gtja_pkl = BASE / 'gtja_signals.pkl.gz'
if gtja_pkl.exists():
    with gzip.open(str(gtja_pkl), 'rb') as f: gtja_data = pickle.load(f)
GTJA_NAMES = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']

def get_gtja(code, dt_str):
    gtja_v = [0.0]*4
    for i,gn in enumerate(GTJA_NAMES):
        sig = gtja_data.get(gn)
        if sig is not None:
            for offset in range(6):
                try: sd = (datetime.strptime(dt_str[:10],'%Y-%m-%d') - timedelta(days=offset)).strftime('%Y-%m-%d')
                except: sd = dt_str[:10]
                if sd in sig.index and code in sig.columns:
                    raw = sig.loc[sd, code]
                    if not np.isnan(raw): gtja_v[i] = float(raw); break
    return gtja_v

# ═══ 2. 辅助数据 ═══
print("[2/5] 预加载数据...")
con = duckdb.connect(str(DB), read_only=True)

all_dates = [str(r[0])[:10] for r in con.execute(
    "SELECT DISTINCT date FROM stock_daily ORDER BY date").fetchall()]
backtest_dates = [d for d in all_dates if START_DATE <= d <= END_DATE]
backtest_set = set(backtest_dates)
print(f"  回测: {backtest_dates[0]}~{backtest_dates[-1]} ({len(backtest_dates)}天)")

idx_data = con.execute(
    "SELECT date, close FROM index_daily WHERE index_code='000001' ORDER BY date").fetchall()
idx_dates = [str(r[0])[:10] for r in idx_data]
idx_closes = np.array([float(r[1]) for r in idx_data])

val_data = {}
val_rows = con.execute("""
    SELECT stock_code, date, pe_ttm, pb, total_mv FROM stock_valuation ORDER BY stock_code, date
""").fetchall()
for code, dt, pe, pb, mv in val_rows:
    ds = str(dt)[:10]; v = {}
    if pe and pe>0: v['ep'] = 1.0/float(pe)
    if pb and pb>0: v['bp'] = 1.0/float(pb)
    if mv and mv>0: v['ln_cap'] = np.log(float(mv))
    if v: val_data[(code, ds)] = v

# 每日活跃股票top300
print("  扫描每日活跃股...")
date_top300 = {}
for dt in backtest_dates:
    rows = con.execute(f"""
        SELECT stock_code, amount FROM stock_daily WHERE date='{dt}' ORDER BY amount DESC LIMIT 300
    """).fetchall()
    date_top300[dt] = {r[0]: float(r[1] or 0) for r in rows}

all_stock_codes = [r[0] for r in con.execute(
    "SELECT stock_code FROM stock_daily GROUP BY stock_code HAVING COUNT(*) >= 160 ORDER BY stock_code"
).fetchall()]
print(f"  股票: {len(all_stock_codes)}只, 每日top300")

# ═══ 特征函数 ═══
def compute_features(c_arr, dt_str, code):
    c = np.array(c_arr[-120:], dtype=np.float64); lc = c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1; chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 else 0; c1d=0.0
    c3d=lc/c[-3]-1 if len(c)>=3 and c[-3]>0 else 0
    v=val_data.get((code,dt_str),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22.0)
    p = idx_dates.index(dt_str) if dt_str in idx_dates else -1
    if p>=20:
        ex5=chg5-(idx_closes[p]/idx_closes[p-5]-1); ex10=chg10-(idx_closes[p]/idx_closes[p-10]-1); ex20=chg20-(idx_closes[p]/idx_closes[p-20]-1)
    else: ex5=ex10=ex20=0.0
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,b1,b2,rr,std20,1.0,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap,ex5,ex10,ex20])

def standardize(f, st, n=23, c3=True):
    for j in range(min(n,len(f))):
        k=f'feat_{j}'; s=st.get(k)
        if s and s['std']>0:
            f[j]=max(f[j],s['low' if not c3 else 'mean']-3*s['std'])
            f[j]=min(f[j],s['high' if not c3 else 'mean']+3*s['std'])
            f[j]=(f[j]-s['mean'])/s['std']
    return f

def predict_triple(c_arr, dt_str, code):
    raw = compute_features(c_arr, dt_str, code)
    gtja = get_gtja(code, dt_str)
    # 20d
    f20 = standardize(raw.copy(), stats20, 23, True)
    f20 = np.nan_to_num(np.append(f20, gtja).reshape(1,-1), nan=0.0)
    p20 = float(reg20.predict(f20)[0])
    # 10d
    f10 = raw.copy()
    for j in range(26):
        k=f'feat_{j}'; s=stats10.get(k)
        if s and s['std']>0:
            f10[j]=max(f10[j],s['low']); f10[j]=min(f10[j],s['high']); f10[j]=(f10[j]-s['mean'])/s['std']
    f10 = np.nan_to_num(np.append(f10, gtja).reshape(1,-1), nan=0.0)
    p10 = float(reg10.predict(f10)[0])
    # 40d
    f40 = raw[:23].copy()
    f40 = standardize(f40, stats40, 23, False)
    f40 = np.nan_to_num(np.append(f40, gtja).reshape(1,-1), nan=0.0)
    p40 = float(reg40.predict(f40)[0])
    return p10, p20, p40

# ═══ 3. 批量预测 ═══
print("\n[3/5] 逐股票预测...")
# data[date][code] = {p10, p20, p40, f10, f20, f40, amount}
data = {}
total = len(all_stock_codes); processed = 0; total_preds = 0

for code in all_stock_codes:
    rows = con.execute(f"""
        SELECT date, close, amount FROM stock_daily WHERE stock_code='{code}' ORDER BY date
    """).fetchall()
    n = len(rows)
    if n < 160: continue
    dates_list = [str(r[0])[:10] for r in rows]
    closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
    amounts = np.array([float(r[2] or 0) for r in rows], dtype=np.float64)
    
    for i in range(119, n - 40):
        dt = dates_list[i]
        if dt not in backtest_set: continue
        if code not in date_top300.get(dt, {}): continue
        
        if dt not in data: data[dt] = {}
        
        try:
            p10, p20, p40 = predict_triple(closes[:i+1], dt, code)
        except: continue
        
        f10 = closes[i+10]/closes[i]-1 if i+10<n else 0
        f20 = closes[i+20]/closes[i]-1 if i+20<n else 0
        f40 = closes[i+40]/closes[i]-1 if i+40<n else 0
        
        data[dt][code] = {
            'p10': p10, 'p20': p20, 'p40': p40,
            'f10': f10, 'f20': f20, 'f40': f40,
            'amt': float(amounts[i]),
        }
        total_preds += 1
    
    processed += 1
    if processed % 300 == 0:
        print(f"  {processed}/{total} stocks, {total_preds} preds [{time.time()-t0:.0f}s]", flush=True)

con.close()
print(f"\n  ✅ {processed} stocks, {total_preds} preds ({time.time()-t0:.0f}s)")

# ═══ 4. 权重枚举 ═══
print("\n[4/5] 权重枚举...")

RESULTS = []

# 枚举范围：10-80%，步长5%
WEIGHTS = list(range(10, 81, 5))  # 15个值
# 只枚举满足 w20+w40+w10=100 的组合
combos = []
for w20 in WEIGHTS:
    for w40 in WEIGHTS:
        w10 = 100 - w20 - w40
        if w10 in WEIGHTS:
            combos.append((w20, w40, w10))
print(f"  组合数: {len(combos)}")

dates_sorted = sorted(data.keys())
N_DAYS = len(dates_sorted)
print(f"  交易日数: {N_DAYS}")

# 预提取所有数据为numpy结构，加速枚举
# 为每个交易日准备 (p10, p20, p40, f20, f40, amt) 数组
# 统一取前300只（按amount排序）
day_stocks = {}  # day -> (codes, p10_arr, p20_arr, p40_arr, f20_arr, f40_arr, amt_arr)
for dt in dates_sorted:
    day_data = data[dt]
    stocks = sorted(day_data.keys(), key=lambda c: day_data[c]['amt'], reverse=True)[:300]
    n = len(stocks)
    if n < 20: continue
    p10s = np.array([day_data[s]['p10'] for s in stocks])
    p20s = np.array([day_data[s]['p20'] for s in stocks])
    p40s = np.array([day_data[s]['p40'] for s in stocks])
    f20s = np.array([day_data[s]['f20'] for s in stocks])
    f40s = np.array([day_data[s]['f40'] for s in stocks])
    amts = np.array([day_data[s]['amt'] for s in stocks])
    day_stocks[dt] = (stocks, p10s, p20s, p40s, f20s, f40s, amts)

print(f"  有效日: {len(day_stocks)}")

MIN_STOCKS = 20
top_idx = 0  # group 0 = top 10%
bot_idx = -1  # group -1 = bottom 10%

for w20, w40, w10 in combos:
    ic20_vals = []; ic40_vals = []; ic_fusion_vals = []
    top_ret20 = []; bot_ret20 = []
    top_ret40 = []; bot_ret40 = []
    
    for dt in dates_sorted:
        if dt not in day_stocks: continue
        stocks, p10s, p20s, p40s, f20s, f40s, amts = day_stocks[dt]
        n = len(stocks)
        if n < MIN_STOCKS * 2: continue
        
        # 计算融合分
        # 先标准化三个模型预测值到0-100
        # 使用rank-based标准化：百分位排名
        def rank_norm(arr):
            if len(arr) < 2: return arr
            ranks = stats.rankdata(arr) / len(arr) * 100
            return ranks
        
        s20 = rank_norm(p20s)
        s10 = rank_norm(p10s)
        s40 = rank_norm(p40s)
        
        fusion = (s20 * w20 + s40 * w40 + s10 * w10) / 100.0
        
        # Fusion IC vs f20
        if len(set(fusion)) >= 2 and len(set(f20s)) >= 2:
            ic_fusion_vals.append(stats.spearmanr(fusion, f20s)[0])
        
        # IC per model
        if len(set(p20s)) >= 2 and len(set(f20s)) >= 2:
            ic20_vals.append(stats.spearmanr(p20s, f20s)[0])
        if len(set(p40s)) >= 2 and len(set(f40s)) >= 2:
            ic40_vals.append(stats.spearmanr(p40s, f40s)[0])
        
        # 分组收益
        n10 = max(n // 10, 2)
        if n10 >= 2:
            # fusion分组
            order = np.argsort(-fusion)  # 降序
            top_ret20.append(np.mean(f20s[order[:n10]]))
            bot_ret20.append(np.mean(f20s[order[-n10:]]))
            
            order40 = np.argsort(-fusion)
            top_ret40.append(np.mean(f40s[order40[:n10]]))
            bot_ret40.append(np.mean(f40s[order40[-n10:]]))
    
    if len(ic_fusion_vals) < 30:
        continue
    
    ic20 = np.mean(ic20_vals) if ic20_vals else 0
    ic40 = np.mean(ic40_vals) if ic40_vals else 0
    ic_f = np.mean(ic_fusion_vals)
    
    spread20 = np.mean(top_ret20) - np.mean(bot_ret20) if top_ret20 else 0
    spread40 = np.mean(top_ret40) - np.mean(bot_ret40) if top_ret40 else 0
    
    win20 = np.mean(np.array(top_ret20) > np.array(bot_ret20)) * 100 if top_ret20 else 0
    
    RESULTS.append({
        'w20': w20, 'w40': w40, 'w10': w10,
        'ic_fusion': round(ic_f, 4), 'ic20': round(ic20, 4), 'ic40': round(ic40, 4),
        'spread20': round(spread20, 4), 'spread40': round(spread40, 4),
        'win20': round(win20, 1),
        'days': len(ic_fusion_vals),
    })

# 排序
RESULTS.sort(key=lambda x: -x['ic_fusion'])
print(f"\n  {'权重(w20/w40/w10)':>20s}  {'IC融':>6s}  {'多空差20':>8s}  {'多空差40':>8s}  {'胜率20':>6s}  {'天数':>5s}")
print("  " + "-" * 60)
for r in RESULTS[:15]:
    print(f"  {r['w20']:3d}/{r['w40']:3d}/{r['w10']:3d}     {r['ic_fusion']:>+6.4f}  {r['spread20']*100:>+7.2f}%  {r['spread40']*100:>+7.2f}%  {r['win20']:>5.0f}%  {r['days']:>5d}")

# 当前权重结果
current = next((r for r in RESULTS if r['w20']==50 and r['w40']==30 and r['w10']==20), None)
if current:
    print(f"\n当前(50/30/20): IC={current['ic_fusion']:+.4f} spread20={current['spread20']*100:+.2f}%")

# 最佳3种
print(f"\n最佳3组:")
for r in RESULTS[:3]:
    print(f"  {r['w20']}/{r['w40']}/{r['w10']} → IC={r['ic_fusion']:+.4f} 多空20={r['spread20']*100:+.2f}% 胜率={r['win20']:.0f}%")

# 额外：仅40d模型效果
single40 = next((r for r in RESULTS if r['w40']==100), None)
if single40:
    print(f"\n仅40d: IC={single40['ic_fusion']:+.4f} spread20={single40['spread20']*100:+.2f}%")

# 按IC均值排序输出完整csv
if RESULTS:
    import csv
    csv_path = OUTPUT / 'weight_enumeration.csv'
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['w20','w40','w10','ic_fusion','ic20','ic40','spread20','spread40','win20','days'])
        w.writeheader()
        w.writerows(RESULTS)
    print(f"\n完整结果: {csv_path}")

print(f"\n总耗时: {time.time()-t0:.0f}s")
