"""
ETF 20d评分模型 v1 — 纯量价特征，基于 fund_daily
"""
import sys, json, time, numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy import stats
from scipy.stats import skew, kurtosis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import get_tushare_db

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

FWD_DAYS = 20
FEAT_WIN = 120
N_FEATS = 24

# 纯量价特征（24维）
FEAT_NAMES = [
    'chg5','chg10','chg20','chg60',
    'd5','d10','d20','d60',
    'bull1','bull2','rr','std20','vr','pos','nh','vpc',
    'c1d','c3d',
    'skew20','dn_streak','up_ratio10',
    'vol_chg','slope5','accel',
]

def compute_etf_features(closes, volumes, pcts):
    """ETF纯量价特征（无估值/无指数对标）"""
    c = np.array(closes[-FEAT_WIN:], dtype=np.float64)
    v = np.array(volumes[-FEAT_WIN:], dtype=np.float64)
    p = np.array(pcts[-FEAT_WIN:], dtype=np.float64)
    lc = c[-1]
    n = len(c)
    
    chg5 = lc/c[-5]-1 if n>=5 else 0
    chg10 = lc/c[-10]-1 if n>=10 else 0
    chg20 = lc/c[-20]-1 if n>=20 else 0
    chg60 = lc/c[-60]-1 if n>=60 else 0
    
    ma5 = np.mean(c[-5:]) if n>=5 else lc
    ma10 = np.mean(c[-10:]) if n>=10 else lc
    ma20 = np.mean(c[-20:]) if n>=20 else lc
    ma60 = np.mean(c[-60:]) if n>=60 else lc
    d5 = lc/ma5-1; d10 = lc/ma10-1; d20 = lc/ma20-1; d60 = lc/ma60-1
    
    bull1 = 1.0 if (ma5>ma10>ma20) else 0.0
    bull2 = 1.0 if (ma20>ma60) else 0.0
    
    w20 = c[-20:] if n>=20 else c
    rl20, rh20 = np.min(w20), np.max(w20)
    rr = (rh20-rl20)/rl20*100 if rl20>0 else 0
    std20 = np.std(w20)/np.mean(w20)*100 if np.mean(w20)>0 else 0
    vols20 = v[-20:] if n>=20 else v
    vr = vols20[-1]/np.mean(vols20) if np.mean(vols20)>0 else 1.0
    pos = (lc-rl20)/(rh20-rl20)*100 if rh20!=rl20 else 50
    nh = 1.0 if lc>rh20*0.97 else 0.0
    vpc = 1.0 if chg5>0 and vr>1.2 else 0.0
    
    c1d = p[-1] if len(p)>0 else 0.0
    c3d = lc/c[-3]-1 if n>=3 else 0.0
    
    skew20_val = float(skew(w20)) if len(w20)>=20 else 0.0
    p20 = np.sign(p[-20:]) if n>=20 else np.sign(p) if len(p)>0 else np.array([0.0])
    dn_streak_val = 0
    for s in reversed(np.sign(p20)):
        if s<0: dn_streak_val += 1
        else: break
    up_ratio10 = np.sum(np.sign(p[-10:])>0)/10.0 if n>=10 else 0.5
    
    vol_chg_val = 0.0
    if n>=60:
        vo = float(np.std(p[-59:-20])*np.sqrt(252))
        vn = float(np.std(p[-20:])*np.sqrt(252))
        vol_chg_val = vn/vo-1 if vo>0 else 0.0
    
    slope5_val = slope10_val = 0.0
    if len(w20)>=10:
        x5=np.arange(5); y5=w20[-5:]
        x10=np.arange(10); y10=w20[-10:]
        d5=np.sum((x5-x5.mean())**2)
        d10=np.sum((x10-x10.mean())**2)
        slope5_val=float(np.sum((x5-x5.mean())*(y5-y5.mean()))/d5) if d5>0 else 0
        slope10_val=float(np.sum((x10-x10.mean())*(y10-y10.mean()))/d10) if d10>0 else 0
    accel_val = slope5_val - slope10_val
    
    return np.array([chg5,chg10,chg20,chg60,
                     d5,d10,d20,d60,
                     bull1,bull2,rr,std20,vr,pos,nh,vpc,
                     c1d,c3d,
                     skew20_val,dn_streak_val,up_ratio10,
                     vol_chg_val,slope5_val,accel_val], dtype=np.float64)

def main():
    t0 = time.time()
    print("="*60, flush=True)
    print("ETF 20d v1 — 纯量价24维", flush=True)
    print(f"窗口={FEAT_WIN}天", flush=True)
    print("="*60, flush=True)
    
    conn = get_tushare_db()
    
    etfs = [r[0] for r in conn.execute("""
        SELECT ts_code FROM fund_basic 
        WHERE list_date IS NOT NULL AND list_date != ''
        ORDER BY list_date DESC
    """).fetchall()]
    print(f"ETF: {len(etfs)}", flush=True)
    
    X_all, y_all = [], []
    t_start = time.time()
    
    for ci, code in enumerate(etfs):
        rows = conn.execute(f"""
            SELECT trade_date, close, vol, COALESCE(pct_chg,0)
            FROM fund_daily WHERE ts_code='{code}'
            ORDER BY trade_date
        """).fetchall()
        if len(rows) < FEAT_WIN + FWD_DAYS + 10:
            continue
        
        closes = [float(r[1]) for r in rows]
        volumes = [float(r[2]) for r in rows]
        pcts = [float(r[3])/100.0 for r in rows]
        
        for i in range(FEAT_WIN, len(rows)-FWD_DAYS):
            feat = compute_etf_features(closes[:i+1], volumes[:i+1], pcts[:i+1])
            ret = float(rows[i+FWD_DAYS][1])/float(rows[i][1]) - 1
            X_all.append(feat)
            y_all.append(ret*100)
        
        if (ci+1) % 200 == 0:
            elapsed = time.time() - t_start
            print(f"  {ci+1}/{len(etfs)}, {len(X_all):,} 样本, {elapsed:.0f}s", flush=True)
    
    conn.close()
    
    X_raw = np.array(X_all, dtype=np.float64)
    y = np.array(y_all, dtype=np.float64)
    print(f"\n总样本: {len(X_raw):,}", flush=True)
    print(f"y范围: {y.min():.2f}~{y.max():.2f}", flush=True)
    
    if len(X_raw) < 10000:
        print(f"样本不足: {len(X_raw)}", flush=True)
        return
    
    n_train = int(len(X_raw)*0.8)
    X_train, y_train = X_raw[:n_train], y[:n_train]
    X_val, y_val = X_raw[n_train:], y[n_train:]
    
    stats_dict = {}
    for j in range(N_FEATS):
        vals = X_raw[:, j]
        valid = vals[~np.isnan(vals) & ~np.isinf(vals)]
        if len(valid)>0:
            stats_dict[f'feat_{j}'] = {
                'mean': float(np.mean(valid)), 'std': float(np.std(valid)),
                'low': float(np.percentile(valid,1)), 'high': float(np.percentile(valid,99)),
            }
    
    def normalize(X, s):
        Xn = X.copy()
        for j in range(N_FEATS):
            key = f'feat_{j}'
            if key in s and s[key]['std']>0:
                Xn[:,j] = np.clip(Xn[:,j], s[key]['low'], s[key]['high'])
                Xn[:,j] = (Xn[:,j] - s[key]['mean']) / s[key]['std']
        return np.nan_to_num(Xn, nan=0.0)
    
    X_train_n = normalize(X_train, stats_dict)
    X_val_n = normalize(X_val, stats_dict)
    
    dtrain = lgb.Dataset(X_train_n, y_train)
    dval = lgb.Dataset(X_val_n, y_val, reference=dtrain)
    
    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 31, 'learning_rate': 0.01,
        'feature_fraction': 0.7, 'bagging_fraction': 0.7, 'bagging_freq': 5,
        'min_data_in_leaf': 100, 'lambda_l1': 0.1, 'lambda_l2': 1.0,
        'max_depth': 6, 'verbose': 1, 'num_threads': 8,
    }
    
    print("\n训练中...", flush=True)
    model = lgb.train(params, dtrain, num_boost_round=3000,
        valid_sets=[dtrain, dval], valid_names=['train','val'],
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(200)])
    
    pred_train = model.predict(X_train_n)
    pred_val = model.predict(X_val_n)
    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]
    
    val_pairs = sorted(zip(pred_val, y_val), key=lambda x: x[0])
    d10 = max(1, len(val_pairs)//10)
    print(f"\n{'='*60}", flush=True)
    print("验证集十分组:", flush=True)
    for d in range(10):
        s,e = d*d10, (d+1)*d10 if d<9 else len(val_pairs)
        rets = [r for _,r in val_pairs[s:e]]
        print(f"  D{d+1}: {np.mean(rets):+.2f}%", flush=True)
    spread = np.mean([r for _,r in val_pairs[-d10:]]) - np.mean([r for _,r in val_pairs[:d10]])
    print(f"  Spread: {spread:+.2f}%", flush=True)
    print(f"  Train IC: {ic_train:.4f}", flush=True)
    print(f"  Val IC:   {ic_val:.4f}", flush=True)
    
    model_path = MODEL_DIR / 'lgb_reg_etf_20d_v1.txt'
    stats_path = MODEL_DIR / 'v_etf_v1_stats.json'
    model.save_model(str(model_path))
    with open(stats_path, 'w') as f:
        json.dump(stats_dict, f)
    
    elapsed = time.time() - t0
    print(f"\n已保存: {model_path}", flush=True)
    print(f"树数: {model.num_trees()}", flush=True)
    print(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)

if __name__ == '__main__':
    main()
