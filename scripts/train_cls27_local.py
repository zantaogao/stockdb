#!/usr/bin/env python3
"""轻量cls27训练 — 500只活跃股 × 20日步长"""
import os, sys, json, time, numpy as np, lightgbm as lgb, duckdb, gzip, pickle
from scipy import stats
from sklearn.metrics import roc_auc_score
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
MODEL_DIR = BASE / 'models'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = MODEL_DIR / 'lgb_cls_model.txt'
OUT_STATS = MODEL_DIR / 'cls27_norm_stats.json'

sys.path.insert(0, str(BASE))
from core.features import compute_raw_features

conn = duckdb.connect(str(DB), read_only=True)

# 取成交额最高的800只
codes = [r[0] for r in conn.execute("""
    SELECT stock_code FROM (
        SELECT stock_code, SUM(amount) as amt FROM stock_daily 
        WHERE date >= '2025-01-01' GROUP BY stock_code ORDER BY amt DESC LIMIT 800
    ) t
""").fetchall()]
print(f'活跃股票: {len(codes)}只', flush=True)

# 加载GTJA
gtja_lookup = {}
if GTJA_PKL.exists():
    with gzip.open(str(GTJA_PKL), 'rb') as f:
        gtja = pickle.load(f)
    for gn in ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']:
        lookup = {}
        for row in gtja.get(gn, []):
            if isinstance(row, dict):
                lookup[(row['stock_code'], str(row['date'])[:10])] = row.get('value', 0)
            elif isinstance(row, (list, tuple)) and len(row) >= 3:
                lookup[(row[0], str(row[1])[:10])] = row[2]
        gtja_lookup[gn] = lookup
    print(f'GTJA: {sum(len(v) for v in gtja_lookup.values())}条', flush=True)

t0 = time.time()
X_list, y_list = [], []

for i, code in enumerate(codes):
    if i % 100 == 0 and i > 0:
        print(f'  {i}/{len(codes)} 股票, {len(X_list)}样本 [{time.time()-t0:.0f}s]', flush=True)
    
    rows = conn.execute(f"""
        SELECT date, close, open, high, low, change_pct, volume, amount
        FROM stock_daily WHERE stock_code='{code}' AND date >= '2023-01-01'
        ORDER BY date ASC
    """).fetchall()
    if len(rows) < 140:
        continue
    
    for j in range(140, len(rows), 20):  # 每20天一个样本
        window = rows[j-120:j][::-1]
        raw, dt_str = compute_raw_features(code, window, conn)
        if raw is None or not dt_str or dt_str >= '2025-06-01':
            continue
        future = rows[j:j+20]
        if len(future) < 20:
            continue
        fwd_ret = (future[-1][1] / rows[j-1][1] - 1) * 100
        gtja_v = [gtja_lookup.get(gn, {}).get((code, dt_str), 0) for gn in ['gtja_006','gtja_083','gtja_177','gtja_184']]
        feat = np.concatenate([raw[:20], raw[20:23], np.array(gtja_v, dtype=np.float64)])
        feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
        X_list.append(feat)
        y_list.append(1 if fwd_ret >= 5.0 else 0)

conn.close()
X, y = np.array(X_list), np.array(y_list)
print(f'\n总样本: {len(X)}  正向率: {y.mean()*100:.1f}%', flush=True)

split = int(len(X) * 0.7)
X_train, X_val, y_train, y_val = X[:split], X[split:], y[:split], y[split:]
print(f'训练: {len(X_train)}  验证: {len(X_val)}', flush=True)

norm_stats = {}
for j in range(27):
    col = X_train[:, j]
    s = float(np.std(col)) if np.std(col) > 0 else 1.0
    norm_stats[f'feat_{j}'] = {'mean': float(np.mean(col)), 'std': s,
        'low': float(np.percentile(col, 1)), 'high': float(np.percentile(col, 99))}
    X_train[:, j] = (X_train[:, j] - norm_stats[f'feat_{j}']['mean']) / s
    X_val[:, j] = (X_val[:, j] - norm_stats[f'feat_{j}']['mean']) / s

json.dump(norm_stats, open(OUT_STATS, 'w'))

model = lgb.LGBMClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
    num_leaves=31, min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
    reg_alpha=0.1, reg_lambda=0.1, class_weight='balanced',
    random_state=42, n_jobs=6, verbose=-1)
model.fit(X_train, y_train, eval_set=[(X_val, y_val)], eval_metric='auc',
          callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)])

prob = model.predict_proba(X_val)[:, 1]
auc = roc_auc_score(y_val, prob)
print(f'\n验证集 AUC: {auc:.4f}', flush=True)

# 分桶
probs_sorted = np.sort(prob)
for p in [10, 20, 30, 50, 70, 80, 90]:
    th = np.percentile(prob, p)
    mask = prob >= th
    hit = y_val[mask].mean() * 100
    print(f'  概率>P{p} ({th:.2f}): {mask.sum():>5}样本  正向率{hit:.1f}%')

model.booster_.save_model(str(OUT_MODEL))
print(f'\n保存: {OUT_MODEL} ({model.booster_.num_trees()}棵树, AUC={auc:.4f})')
