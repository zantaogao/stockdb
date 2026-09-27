"""40d 全窗口样本重建 v7（2026-09-26，用户批准"今晚建+训+上线"）
口径 = _cron_retrain_build_0926.py 逐字对齐生产 core/scoring.py，两点差异：
  1. F40_START 取消——全窗口都产 40d 行（y40=+40交易日收益%）
  2. f34=ex5 新维（用户拍板纳入 ex；ex10/ex20 不加，单维试验）
输出: (date, code, f0..f25=BASE_KEEP26, f31..f33=stk因子3维, f34=ex5, y40)
      → analysis/retrain_20260926/samples_40d_v7.parquet
训练: 10% 尾截 + winsorize + z-score + 去泄漏 + 80/20 时间切分（同 PC train.py 纪律）
"""
import json, time, sys, os
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy import stats
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data, get_factor_from_db
from core.db import get_tushare_db

BASE = '/Users/zantao/.hermes/stockdb'
OUT = BASE + '/analysis/retrain_20260926'
from pathlib import Path
OUTP = Path(OUT)
SAMPLE_START = '20160101'
FEAT_WIN = 60
BASE_KEEP = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
FACTOR_FIELDS = ['kdj_k', 'cci', 'rsi_12']
FC = ['f%d' % j for j in range(26)] + ['f31','f32','f33','f34']

os.nice(10)
conn = get_tushare_db()
stocks = [r[0] for r in conn.execute(
    "SELECT symbol FROM stock_basic WHERE market != '北交所' AND (name NOT LIKE '%ST%' OR name IS NULL) "
    "AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%' AND symbol NOT LIKE '92%'").fetchall()]
print(f'股票池: {len(stocks)}', flush=True)

cal = [str(r[0]) for r in conn.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE trade_date >= ? ORDER BY 1", [SAMPLE_START]).fetchall()]
cal_idx = {d: i for i, d in enumerate(cal)}
idx_data = load_index_data()
print(f'日历: {len(cal)}天 {cal[0]}~{cal[-1]}', flush=True)

val_rows = conn.execute(
    "SELECT ts_code, trade_date, pe_ttm, pb, total_mv FROM daily_basic WHERE trade_date >= ? ORDER BY ts_code, trade_date",
    [SAMPLE_START]).fetchall()
val_by_code = {}
for ts, d, pe, pb, mv in val_rows:
    dd = {}
    if pe and float(pe) > 0: dd['ep'] = 1.0/float(pe)
    if pb and float(pb) > 0: dd['bp'] = 1.0/float(pb)
    if mv and float(mv) > 0: dd['ln_cap'] = np.log(float(mv))
    val_by_code.setdefault(ts, {})[str(d)] = dd
print(f'daily_basic {len(val_rows):,} 行', flush=True)

sf_rows = conn.execute(
    "SELECT ts_code, trade_date, kdj_k, cci, rsi_12 FROM stk_factor WHERE trade_date >= ? ORDER BY ts_code, trade_date",
    [SAMPLE_START]).fetchall()
fac_by_code = {}
for ts, d, k, c, r in sf_rows:
    fac_by_code.setdefault(ts, {})[str(d)] = [
        float(k) if k is not None else 0.0, float(c) if c is not None else 0.0, float(r) if r is not None else 0.0]
print(f'stk_factor {len(sf_rows):,} 行', flush=True)

rows40, batch_i = [], 0
(OUTP / 'batches_v7').mkdir(exist_ok=True)
t0 = time.time(); miss_val = bad_feat = 0

def flush(force=False):
    global rows40, batch_i
    if len(rows40) < 100000 and not force: return
    pd.DataFrame(rows40, columns=['date','code']+FC+['y40']).to_parquet(
        str(OUTP / f'batches_v7/b{batch_i:03d}.parquet'), index=False)
    batch_i += 1
    print(f'  FLUSH {len(rows40):,} 累计批{batch_i} {time.time()-t0:.0f}s', flush=True)
    rows40 = []

for ci, code in enumerate(stocks):
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code}' AND trade_date >= '{SAMPLE_START}' ORDER BY trade_date
    """).fetchall()
    if len(rows) < FEAT_WIN + 41: continue
    closes = [float(r[1]) for r in rows]; highs_raw = [float(r[3]) for r in rows]
    lows_raw = [float(r[4]) for r in rows]; pcts = [float(r[5])/100.0 for r in rows]
    volumes = [float(r[6]) for r in rows]; dates = [str(r[0]) for r in rows]
    adj_rows = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts_code]).fetchall()
    adj_closes, adj_highs, adj_lows = apply_forward_adjust(closes, highs_raw, lows_raw, adj_rows)
    board_idx = get_board_index(code); idx_info = idx_data.get(board_idx)
    lab = {str(r[0]): float(r[1]) for r in conn.execute(
        f"SELECT trade_date, close FROM daily WHERE ts_code='{ts_code}' AND trade_date >= '{SAMPLE_START}'").fetchall()}
    vmap = val_by_code.get(ts_code, {}); fmap = fac_by_code.get(ts_code, {})

    for i in range(FEAT_WIN, len(rows) - 40):
        d = dates[i]
        di = cal_idx.get(d)
        if di is None or di < 20: continue
        idx_closes = None
        if idx_info:
            idx_closes = {dd: idx_info['dict'][dd] for dd in sorted(idx_info['dict']) if dd <= d}
            if len(idx_closes) < 20: idx_closes = None
        val_dict = vmap.get(d)
        if val_dict is None:
            miss_val += 1; val_dict = {}
        feat_38 = compute_features(adj_closes[i-FEAT_WIN:i+1], adj_highs[i-FEAT_WIN:i+1], adj_lows[i-FEAT_WIN:i+1],
                                   volumes[i-FEAT_WIN:i+1], pcts[i-FEAT_WIN:i+1], idx_closes, val_dict)
        if feat_38 is None: continue
        feat_38 = list(feat_38)
        if len(feat_38) != 38:
            bad_feat += 1; continue
        base = adj_closes[i]
        c40 = lab.get(dates[i+40])
        if c40 is None or base <= 0: continue
        keep26 = [float(feat_38[j]) for j in BASE_KEEP]
        ex5 = float(feat_38[23])
        rows40.append((d, code, *(keep26 + fmap.get(d, [0.0,0.0,0.0]) + [ex5]), (c40/base-1)*100))
    if (ci+1) % 300 == 0:
        flush()
        print(f'  {ci+1}/{len(stocks)} {time.time()-t0:.0f}s 缺估值{miss_val} 坏特征{bad_feat}', flush=True)

flush(force=True)
conn.close()

# 汇总去重
import duckdb
con = duckdb.connect()
con.execute(f"COPY (SELECT DISTINCT ON (date, code) * FROM read_parquet('{OUT}/batches_v7/*.parquet') ORDER BY date, code) TO '{OUT}/samples_40d_v7.parquet' (FORMAT PARQUET)")
r = con.execute(f"SELECT COUNT(*), MIN(date), MAX(date), STDDEV(f34), AVG(ABS(f34)) FROM read_parquet('{OUT}/samples_40d_v7.parquet')").fetchone()
print(f'样本v7: {r[0]:,}行 {r[1]}~{r[2]} ex5(f34) std={r[3]:.4f} |v|={r[4]:.4f}', flush=True)
con.close()

# ============ 训练（PC train.py 同法，80/20 时间切分 + 训练段 winsor/z） ============
df = pd.read_parquet(OUT + '/samples_40d_v7.parquet')
df['date'] = df['date'].astype(str)
feats = FC
dates_u = np.sort(df['date'].unique())
split = dates_u[int(len(dates_u)*0.8)]
tr = df[df['date'] < split]; va = df[df['date'] >= split]
print(f'切分 {split} 训 {len(tr):,} 验 {len(va):,}', flush=True)
Xtr = tr[feats].to_numpy(float).copy(); Xva = va[feats].to_numpy(float).copy()
ytr = tr['y40'].to_numpy(float); yva = va['y40'].to_numpy(float)
# 去泄漏: 训练段 y 1% 尾截
lo, hi = np.percentile(ytr, 1), np.percentile(ytr, 99); ytr = np.clip(ytr, lo, hi)
stats_dict = {}
for j in range(len(feats)):
    v = Xtr[:, j]; v = v[np.isfinite(v)]
    l_, h_ = np.percentile(v, 1), np.percentile(v, 99)
    mu, sd = float(v.mean()), float(v.std())
    stats_dict[f'feat_{j}'] = {'mean': mu, 'std': sd or 1.0, 'low': float(l_), 'high': float(h_)}
    Xtr[:, j] = (np.clip(Xtr[:, j], l_, h_) - mu)/sd
    Xva[:, j] = (np.clip(Xva[:, j], l_, h_) - mu)/sd
Xtr = np.nan_to_num(Xtr, nan=0.0); Xva = np.nan_to_num(Xva, nan=0.0)
params = {'objective':'regression','metric':'l2','num_leaves':15,'learning_rate':0.01,
          'feature_fraction':0.7,'bagging_fraction':0.7,'bagging_freq':5,
          'min_data_in_leaf':200,'lambda_l1':0.3,'lambda_l2':2.0,'max_depth':5,
          'verbose':1,'num_threads':8}
dtrain = lgb.Dataset(Xtr, ytr); dval = lgb.Dataset(Xva, yva, reference=dtrain)
t1 = time.time()
model = lgb.train(params, dtrain, num_boost_round=2000, valid_sets=[dtrain, dval],
                  valid_names=['train','val'], callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)])
print(f'训练 {time.time()-t1:.0f}s 树数 {model.num_trees()} best {model.best_iteration}', flush=True)
pred = model.predict(Xva)
dts = va['date'].to_numpy(); ics = []
for d in np.unique(dts):
    m = dts == d
    if m.sum() >= 200: ics.append(stats.spearmanr(pred[m], yva[m])[0])
print(f'40d新 验证日均IC {np.mean(ics):+.4f} (n={len(ics)}天) 正IC占比 {np.mean([i>0 for i in ics])*100:.0f}%', flush=True)
pairs = sorted(zip(pred, yva), key=lambda x: x[0]); d10 = max(1, len(pairs)//10)
print('十分组: ' + ' '.join(f'D{i+1}:{np.mean([r for _,r in (pairs[i*d10:(i+1)*d10] if i<9 else pairs[9*d10:])])*100:+.2f}%' for i in range(10)), flush=True)
s = model.feature_importance('split'); o = sorted(range(len(feats)), key=lambda i: -s[i])
print('ex5(f34) split排名:', o.index(len(feats)-1)+1, '/', len(feats), f'split={s[-1]}', flush=True)
model.save_model(OUT + '/lgb_reg_40d_v7.txt')
json.dump(stats_dict, open(OUT + '/v40_v7_stats.json','w'))
json.dump({'trained_at': time.strftime('%F %T'), 'samples_file': 'samples_40d_v7.parquet',
           'n_samples': int(len(df)), 'n_features': len(feats), 'date_range': [str(df.date.min()), str(df.date.max())],
           'split_date': str(split), 'n_train': int(len(tr)), 'n_val': int(len(va)), 'params': params,
           'val_daily_rank_ic_mean': float(np.mean(ics)), 'val_days': len(ics),
           'pos_ic_ratio': float(np.mean([i>0 for i in ics])),
           'ex5_split_rank': int(o.index(len(feats)-1))+1},
          open(OUT + '/train_40d_v7_results.json','w'), indent=1, ensure_ascii=False)
print('SAVED lgb_reg_40d_v7.txt', flush=True)
