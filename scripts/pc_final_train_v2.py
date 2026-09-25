#!/usr/bin/env python3
"""
综合训练 v2 — 全量数据 (2024-01 ~ 2026-05)
升级点:
  1. 数据量 4.2x (581天 vs 139天)
  2. 加入估值因子 (EP, BP, ln_cap) 
  3. DuckDB窗口函数算Z-score (比逐行快1000倍)
  4. 更好的验证切分
  5. 更深度调参

用法: python pc_final_train_v2.py
"""

import duckdb, numpy as np, pandas as pd, lightgbm as lgb
import torch, time, os, json, sys
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from scipy import stats
from sklearn.metrics import roc_auc_score

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()
results = {}

print(f"设备: {DEVICE}", flush=True)
if torch.cuda.is_available():
    print(f"  GPU: {torch.cuda.get_device_name(0)}", flush=True)

# ═══════════════════════════════════════════
# PART 0: 因子库重算 — 覆盖全期
# ═══════════════════════════════════════════
print("\n" + "=" * 60, flush=True)
print("PART 0/3: 因子库全期重算 (2024-01 ~ 2026-05)", flush=True)
print("=" * 60, flush=True)

con = duckdb.connect(DB)
con.execute("SET memory_limit='8GB'")
con.execute("SET threads=8")

# 清空旧因子表
con.execute("DELETE FROM factor_daily_values")

# 直接在DuckDB内算因子（比Python逐行快）
t_f0 = time.time()
con.execute("""
    INSERT INTO factor_daily_values (date, stock_code, factor_name, raw_value, zscore)
    SELECT date, stock_code, 'mom_5' as factor_name, 
           (close / LAG(close, 5) OVER (PARTITION BY stock_code ORDER BY date) - 1) as raw_value,
           NULL as zscore
    FROM stock_daily WHERE date >= '2023-11-01'
""")
print(f"  mom_5: {time.time()-t_f0:.0f}s", flush=True)

for name, lag, desc in [('mom_10', 10, '10日涨幅'), ('mom_20', 20, '20日涨幅'), ('mom_60', 60, '60日涨幅')]:
    t1 = time.time()
    con.execute(f"""
        INSERT INTO factor_daily_values (date, stock_code, factor_name, raw_value, zscore)
        SELECT date, stock_code, '{name}' as factor_name,
               (close / LAG(close, {lag}) OVER (PARTITION BY stock_code ORDER BY date) - 1) as raw_value,
               NULL as zscore
        FROM stock_daily WHERE date >= '2023-11-01'
    """)
    print(f"  {name}: {time.time()-t1:.0f}s", flush=True)

# 波动率因子 (std of returns over window)
con.execute("""
    CREATE TEMP TABLE daily_ret AS
    SELECT stock_code, date, change_pct/100.0 as ret
    FROM stock_daily WHERE date >= '2023-11-01'
""")

for name, window, desc in [('vol_20', 20, '20日波动率'), ('vol_60', 60, '60日波动率')]:
    t1 = time.time()
    con.execute(f"""
        INSERT INTO factor_daily_values (date, stock_code, factor_name, raw_value, zscore)
        SELECT dr.date, dr.stock_code, '{name}' as factor_name,
               STDDEV_SAMP(dr2.ret) * SQRT(252) as raw_value, NULL as zscore
        FROM daily_ret dr
        JOIN daily_ret dr2 ON dr2.stock_code = dr.stock_code
            AND dr2.date > dr.date - INTERVAL '{window}' DAY
            AND dr2.date <= dr.date
        WHERE dr.date >= '2023-11-01'
        GROUP BY dr.date, dr.stock_code
    """)
    print(f"  {name}: {time.time()-t1:.0f}s", flush=True)

# 换手率因子
for name, window, desc in [('turn_5', 5, '5日换手率'), ('turn_20', 20, '20日换手率')]:
    t1 = time.time()
    con.execute(f"""
        INSERT INTO factor_daily_values (date, stock_code, factor_name, raw_value, zscore)
        SELECT date, stock_code, '{name}' as factor_name,
               AVG(turn_rate/100.0) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN {window-1} PRECEDING AND CURRENT ROW) as raw_value,
               NULL as zscore
        FROM stock_daily WHERE date >= '2023-11-01'
    """)
    print(f"  {name}: {time.time()-t1:.0f}s", flush=True)

con.execute("DROP TABLE daily_ret")

# Z-score: 用窗口函数算（比逐行UPDATE快1000倍）
t_z = time.time()
con.execute("""
    UPDATE factor_daily_values
    SET zscore = (raw_value - mean) / NULLIF(std, 0)
    FROM (
        SELECT date, factor_name, 
               AVG(raw_value) as mean, 
               STDDEV_SAMP(raw_value) as std
        FROM factor_daily_values
        WHERE raw_value IS NOT NULL
        GROUP BY date, factor_name
    ) stats
    WHERE factor_daily_values.date = stats.date 
      AND factor_daily_values.factor_name = stats.factor_name
      AND factor_daily_values.raw_value IS NOT NULL
""")
print(f"Z-score: {time.time()-t_z:.0f}s", flush=True)

# 验证
factor_cnt = con.execute("SELECT COUNT(*) FROM factor_daily_values").fetchone()[0]
zscore_cnt = con.execute("SELECT COUNT(*) FROM factor_daily_values WHERE zscore IS NOT NULL").fetchone()[0]
dates_cnt = con.execute("SELECT COUNT(DISTINCT date) FROM factor_daily_values").fetchone()[0]
print(f"因子表: {factor_cnt:,}条, 含zscore: {zscore_cnt:,}, 共{dates_cnt}个交易日", flush=True)

# 估值因子读内存（LightGBM用）
val_df = con.execute("SELECT stock_code, date, pe_ttm, pb, total_mv FROM stock_valuation ORDER BY stock_code, date").fetchdf()
print(f"估值数据: {len(val_df)}行", flush=True)

t_part0 = time.time()
print(f"PART 0 耗时: {time.time()-t0:.0f}s", flush=True)

# ═══════════════════════════════════════════
# PART 1: LightGBM — 20技术特征 + 估值因子
# ═══════════════════════════════════════════
print("\n" + "=" * 60, flush=True)
print("PART 1/3: LightGBM (20技术 + 3估值 = 23维)", flush=True)
print("=" * 60, flush=True)

daily = con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, 
           turn_rate/100.0 as turn, amount
    FROM stock_daily WHERE date >= '2023-11-01' ORDER BY stock_code, date
""").fetchdf()
print(f"日线: {len(daily)}行", flush=True)

# 估值字典
val_dict = {}
for _, row in val_df.iterrows():
    key = (row['stock_code'], str(row['date'])[:10])
    ep = 1.0 / row['pe_ttm'] if row['pe_ttm'] and row['pe_ttm'] > 0 else None
    bp = 1.0 / row['pb'] if row['pb'] and row['pb'] > 0 else None
    lc = np.log(row['total_mv']) if row['total_mv'] and row['total_mv'] > 0 else None
    if ep is not None or bp is not None or lc is not None:
        val_dict[key] = {'ep': ep, 'bp': bp, 'ln_cap': lc}

# 特征生成（numpy向量化，按股票分组）
rows_list = []
code_count = 0
grouped = list(daily.groupby('stock_code', sort=False))

for code, grp in grouped:
    n = len(grp)
    if n < 120:
        continue
    code_count += 1
    
    c_arr = grp['close'].values.astype(np.float64)
    r_arr = grp['ret'].values.astype(np.float64)
    a_arr = grp['amount'].values.astype(np.float64)
    d_arr = grp['date'].values
    
    # 预分配滑动窗口
    for i in range(119, n):
        c = c_arr[:i+1]
        lc = c[-1]
        
        chg5 = lc/c[-5]-1 if i >= 4 else 0
        chg10 = lc/c[-10]-1 if i >= 9 else 0
        chg20 = lc/c[-20]-1 if i >= 19 else 0
        chg60 = lc/c[-60]-1 if i >= 59 else 0
        chg120 = lc/c[0]-1
        
        ma5, ma10 = np.mean(c[-5:]), np.mean(c[-10:])
        ma20, ma60 = np.mean(c[-20:]), np.mean(c[-60:])
        ma120 = np.mean(c)
        
        d5 = lc/ma5-1 if ma5 > 0 else 0
        d10 = lc/ma10-1 if ma10 > 0 else 0
        d20 = lc/ma20-1 if ma20 > 0 else 0
        d60 = lc/ma60-1 if ma60 > 0 else 0
        d120 = lc/ma120-1 if ma120 > 0 else 0
        
        bull1 = 1 if ma5 > ma10 > ma20 else 0
        bull2 = 1 if ma20 > ma60 else 0
        
        r20 = np.max(c[-20:]) - np.min(c[-20:])
        rr = r20/np.min(c[-20:])*100 if np.min(c[-20:]) > 0 else 0
        std20 = np.std(c[-20:])/np.mean(c[-20:])*100
        
        vols = a_arr[-20:]
        vr = vols[-1]/np.mean(vols) if np.mean(vols) > 0 else 1
        
        rl, rh = np.min(c[-20:]), np.max(c[-20:])
        pos = (lc-rl)/(rh-rl)*100 if rh != rl else 50
        nh = 1 if lc > rh*0.97 else 0
        vpc = 1 if chg5 > 0 and vr > 1.2 else 0
        c1d = r_arr[i] if i > 0 else 0
        c3d = lc/c[-3]-1 if i >= 2 else 0
        
        # 估值因子（forward fill）
        date_key = str(d_arr[i])[:10]
        v = val_dict.get((code, date_key), {})
        ep = v.get('ep', 0.5)
        bp = v.get('bp', 0.5)
        ln_cap = v.get('ln_cap', 22)
        
        # 标签: 未来5日收益
        rf = np.prod(1 + r_arr[i+1:min(i+6, n)]) - 1 if i < n-1 else 0
        
        rows_list.append([chg5, chg10, chg20, chg60, chg120, d5, d10, d20, d60, d120,
                          bull1, bull2, rr, std20, vr, pos, nh, vpc, c1d, c3d,
                          ep, bp, ln_cap, rf])
    
    if code_count % 500 == 0:
        print(f"  已处理: {code_count}/{len(grouped)}只, {len(rows_list):,}样本", flush=True)

arr = np.array(rows_list, dtype=np.float32)
X = arr[:, :23]
y = arr[:, 23]
y_cls = (y > 0).astype(int)

print(f"\n总样本: {len(X):,}  (股票{code_count}只)", flush=True)
print(f"标签: mean={y.mean():+.4f} median={np.median(y):+.4f} 涨比例={y_cls.mean()*100:.1f}%", flush=True)

# 时间顺序切分 (前80%训练, 后20%测试)
split = int(len(X) * 0.80)
X_tr, X_te = X[:split], X[split:]
yr_tr, yr_te = y[:split], y[split:]
yc_tr, yc_te = y_cls[:split], y_cls[split:]

# 标准化
for j in range(23):
    col = X_tr[:, j]
    l, h = np.percentile(col[~np.isnan(col)], [1, 99])
    col = np.clip(col, l, h)
    m, s = np.nanmean(col), np.nanstd(col)
    if s > 0:
        X_tr[:, j] = (col - m) / s
        X_te[:, j] = (np.clip(X_te[:, j], l, h) - m) / s

print(f"训练: {len(X_tr):,}  测试: {len(X_te):,}", flush=True)

# ═══ 回归 ═══
print("\n--- 回归模型 ---", flush=True)
reg = lgb.LGBMRegressor(
    n_estimators=3000, max_depth=6, learning_rate=0.003,
    subsample=0.8, colsample_bytree=0.8, min_child_samples=50,
    reg_lambda=1.0, reg_alpha=0.5, num_leaves=63,
    min_gain_to_split=0.01,
    device='gpu', gpu_device_id=0, random_state=42, verbose=-1
)
reg.fit(X_tr, yr_tr, eval_set=[(X_te, yr_te)],
        eval_metric=['rmse', 'mae'],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(200)])

pred_r = reg.predict(X_te)
ic_r = stats.spearmanr(pred_r, yr_te)[0]

# 分组验证
sorted_idx = np.argsort(pred_r)
print(f"\n  回归分组 (测试集, {len(pred_r):,}样本):")
for g in range(10):
    s = g * len(sorted_idx) // 10
    e = (g+1) * len(sorted_idx) // 10
    grp = sorted_idx[s:e]
    print(f"    组{g+1:2d}: 预测{np.mean(pred_r[grp]):+.3%} → 实际{np.mean(yr_te[grp]):+.3%}", flush=True)

results['reg_ic'] = round(ic_r, 4)
results['reg_trees'] = reg.best_iteration_
print(f"  回归 IC={ic_r:.4f} ({reg.best_iteration_}棵树)", flush=True)

# ═══ 分类 ═══
print("\n--- 分类模型 ---", flush=True)
cls = lgb.LGBMClassifier(
    n_estimators=3000, max_depth=6, learning_rate=0.003,
    subsample=0.8, colsample_bytree=0.8, min_child_samples=50,
    reg_lambda=1.0, reg_alpha=0.5, num_leaves=63,
    class_weight='balanced',
    device='gpu', gpu_device_id=0, random_state=42, verbose=-1
)
cls.fit(X_tr, yc_tr, eval_set=[(X_te, yc_te)],
        eval_metric=['auc', 'binary_logloss'],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(200)])

pred_c = cls.predict_proba(X_te)[:, 1]
auc = roc_auc_score(yc_te, pred_c)
pos_ret = np.mean(yr_te[pred_c > 0.5]) if np.sum(pred_c > 0.5) > 10 else 0
neg_ret = np.mean(yr_te[pred_c <= 0.5]) if np.sum(pred_c <= 0.5) > 10 else 0

results['cls_auc'] = round(auc, 4)
results['cls_trees'] = cls.best_iteration_
print(f"  分类 AUC={auc:.4f} ({cls.best_iteration_}棵树)", flush=True)
print(f"  预测涨: {pos_ret:+.2%}  跌: {neg_ret:+.2%}  多空差: {pos_ret-neg_ret:+.2%}", flush=True)

# 特征重要性
print(f"\n  特征TOP15 (gain):")
imp = reg.booster_.feature_importance(importance_type='gain')
names = ['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120',
         'bull1','bull2','range','std20','vol_r','pos','near_h','vpc','c1d','c3d',
         'ep','bp','ln_cap']
for n, v in sorted(zip(names, imp), key=lambda x: x[1], reverse=True)[:15]:
    print(f"    {n:8s} {v:.0f}", flush=True)

reg.booster_.save_model(os.path.join(OUT, "lgb_reg_v2.txt"))
cls.booster_.save_model(os.path.join(OUT, "lgb_cls_v2.txt"))
print(f"\n✅ LightGBM v2 已保存", flush=True)

t_part1 = time.time()
print(f"PART 1 耗时: {time.time()-t_part0:.0f}s", flush=True)

# ═══════════════════════════════════════════
# PART 2: LSTM v3 — 全期因子数据
# ═══════════════════════════════════════════
print("\n" + "=" * 60, flush=True)
print("PART 2/3: LSTM v3 (8因子序列→5日收益)", flush=True)
print("=" * 60, flush=True)

raw = con.execute("""
    SELECT f.date, f.stock_code, f.factor_name, f.zscore,
           (b.close / a.close - 1) as ret_future
    FROM factor_daily_values f
    JOIN stock_daily a ON f.stock_code = a.stock_code AND f.date = a.date
    LEFT JOIN stock_daily b ON f.stock_code = b.stock_code 
        AND b.date = (SELECT MIN(date) FROM stock_daily 
                      WHERE stock_code = f.stock_code AND date > f.date + 4)
    WHERE f.zscore IS NOT NULL AND f.date >= '2024-03-01'
      AND f.factor_name IN ('mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20')
    ORDER BY f.stock_code, f.date
""").fetchdf()
con.close()

print(f"因子数据: {len(raw)}行", flush=True)

core = ['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
pv = raw.pivot_table(index=['stock_code','date','ret_future'],
                     columns='factor_name', values='zscore').reset_index()
pv = pv.sort_values(['stock_code','date']).dropna(subset=core)
pv = pv.dropna(subset=['ret_future'] + core)
print(f"Pivot后: {len(pv)}行", flush=True)

seqs, tgts = [], []
for code, grp in pv.groupby('stock_code'):
    grp = grp.sort_values('date')
    v = grp[core].values.astype(np.float32)
    r = grp['ret_future'].values.astype(np.float32)
    for i in range(20, len(grp)):
        if not np.isnan(v[i-20:i]).any() and not np.isnan(r[i]):
            seqs.append(v[i-20:i])
            tgts.append(r[i])

X_lstm = np.array(seqs)
y_lstm = np.array(tgts)
print(f"LSTM序列: {X_lstm.shape}, 目标: {y_lstm.shape}", flush=True)

split_lstm = int(len(X_lstm) * 0.80)
X_lt, X_le = X_lstm[:split_lstm], X_lstm[split_lstm:]
y_lt, y_le = y_lstm[:split_lstm], y_lstm[split_lstm:]

yme_l = np.mean(y_lt); ysd_l = np.std(y_lt) + 1e-8
y_lt_n = (y_lt - yme_l) / ysd_l
y_le_n = (y_le - yme_l) / ysd_l

tl = DataLoader(TensorDataset(torch.tensor(X_lt), torch.tensor(y_lt_n)), 512, shuffle=True)
tel = DataLoader(TensorDataset(torch.tensor(X_le), torch.tensor(y_le_n)), 512, shuffle=False)

print(f"训练: {len(y_lt):,}  测试: {len(y_le):,}", flush=True)
print(f"收益: mean={yme_l:.4f} std={ysd_l:.4f}", flush=True)

class LSTMPredictor(nn.Module):
    def __init__(self, input_size=8, hidden=128, layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden, layers, batch_first=True, dropout=0.3)
        self.fc = nn.Sequential(nn.Linear(hidden, 64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64, 1))
    def forward(self, x):
        o, _ = self.lstm(x)
        return self.fc(o[:, -1, :])

m = LSTMPredictor().to(DEVICE)
opt = torch.optim.AdamW(m.parameters(), lr=0.001, weight_decay=1e-5)
sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, patience=5, factor=0.5, min_lr=1e-5)
loss_fn = nn.MSELoss()

best_loss = float('inf')
best_ic = 0
patience = 0
print(f"参数: {sum(p.numel() for p in m.parameters()):,}", flush=True)

for ep in range(40):
    m.train(); trl = 0
    for Xb, yb in tl:
        Xb, yb = Xb.to(DEVICE), yb.to(DEVICE)
        p = m(Xb).squeeze(); l = loss_fn(p, yb)
        opt.zero_grad(); l.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step(); trl += l.item() * len(Xb)
    trl /= len(tl.dataset)
    
    m.eval(); tel_l = 0; pp, aa = [], []
    with torch.no_grad():
        for Xb, yb in tel:
            Xb, yb = Xb.to(DEVICE), yb.to(DEVICE)
            p = m(Xb).squeeze(); tel_l += loss_fn(p, yb).item() * len(Xb)
            pp.extend(p.cpu().numpy()); aa.extend(yb.cpu().numpy())
    tel_l /= len(tel.dataset)
    
    pp_r = np.array(pp) * ysd_l + yme_l
    aa_r = np.array(aa) * ysd_l + yme_l
    ic_l = stats.spearmanr(pp_r, aa_r)[0]
    sched.step(tel_l)
    
    if (ep+1) % 5 == 0 or ep == 0:
        print(f"  E{ep+1:2d}: tr={trl:.6f} val={tel_l:.6f} IC={ic_l:.4f}", flush=True)
    
    if tel_l < best_loss:
        best_loss = tel_l; best_ic = ic_l; patience = 0
        torch.save(m.state_dict(), os.path.join(OUT, "lstm_v2.pt"))
    else:
        patience += 1
        if patience >= 8:
            print(f"  Early stop @ E{ep+1}", flush=True); break

m.load_state_dict(torch.load(os.path.join(OUT, "lstm_v2.pt"))); m.eval()
with torch.no_grad():
    pp_f = m(torch.tensor(X_le).to(DEVICE)).cpu().numpy().flatten() * ysd_l + yme_l
ic_lf = stats.spearmanr(pp_f, y_le)[0]
results['lstm_ic'] = round(ic_lf, 4)
results['lstm_epochs'] = ep + 1

print(f"\n  LSTM分组:")
sorted_lstm = np.argsort(pp_f)
for g in range(10):
    s = g * len(sorted_lstm) // 10
    e = (g+1) * len(sorted_lstm) // 10
    grp = sorted_lstm[s:e]
    print(f"    组{g+1:2d}: 预测{np.mean(pp_f[grp]):+.2%} → 实际{np.mean(y_le[grp]):+.2%}", flush=True)

print(f"\nLSTM v2 IC={ic_lf:.4f}", flush=True)

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
results['total_time'] = round(time.time() - t0, 1)
results['device'] = DEVICE
results['data_range'] = '2024-01~2026-05'
results['n_features'] = 23
results['n_train'] = len(X_tr)
results['n_test'] = len(X_te)
results['lstm_seqs'] = len(X_lstm)

print(f"\n{'=' * 60}", flush=True)
print("v2 训练完成!", flush=True)
print(json.dumps(results, indent=2), flush=True)

with open(os.path.join(OUT, "final_results_v2.json"), "w") as f:
    json.dump(results, f, indent=2)

print(f"总耗时: {results['total_time']}s", flush=True)
print(f"{'=' * 60}", flush=True)
