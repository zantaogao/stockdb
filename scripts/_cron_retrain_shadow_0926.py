#!/usr/bin/env python3
"""三模型重训·影子打分（每晚挂，2026-09-26 建）
对 signal_history 最新信号日（新模型产出之后），用新模型三件套 + 新 stats 全市场打分：
  - 10d_v5 / 20d_v2: 31维 PV 口径（从 tushare.db daily 现算 feat38 → PV_INDICES → 新 stats 标准化）
  - 40d_inc: 29维含因子口径（与生产 core/scoring.py 一致：26 BASE + stk_factor extra _bfq 3因子 → 旧stats 口径由增量训练保证）
写入 signals.db:
  shadow_v10d_v5_scores / shadow_v20d_v2_scores / shadow_v40d_inc_scores (date, code, score)
IC 对拍由 ic_daily/442 链消费。生产 fusion_score 不动——换产判据=成熟日≥30 + NW-t≥2 + 均值差>0。
"""
import sys, os, time, json
import numpy as np
import pandas as pd
import sqlite3, lightgbm as lgb
from pathlib import Path

BASE = Path.home() / '.hermes/stockdb'
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / 'scripts'))
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data, get_factor_from_db

MODELS_DIR = BASE / 'models'
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
BASE_KEEP = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
FACTOR_FIELDS = ['kdj_k', 'cci', 'rsi_12']
FEAT_WIN = 60

# 修(0927): 0926重训的10d_v5未在本机models/落盘(训练在PC侧)，影子10d腿暂用生产在用的10d_v3(同31维PV口径,当日重打分仍有效)
m10 = lgb.Booster(model_file=str(MODELS_DIR / 'lgb_reg_10d_v3.txt'))
s10 = json.load(open(MODELS_DIR / 'v10_v3_stats.json'))  # 修(0927): 同v3模型配套stats(旧引用v5 stats未落盘)
m20 = lgb.Booster(model_file=str(MODELS_DIR / 'lgb_reg_20d_v2.txt'))
s20 = json.load(open(MODELS_DIR / 'v20_v2_stats.json'))
m40 = lgb.Booster(model_file=str(MODELS_DIR / 'lgb_reg_40d_inc_v2.txt'))
s40 = json.load(open(MODELS_DIR / 'retired_20260926/v6_norm_stats_40d_tushare_v2_stkfactor.json'))  # 0927: 增量影子腿用退役归档stats(随模型同归档)

def standardize(X, st):
    X = X.copy()
    for j in range(X.shape[1]):
        k = f'feat_{j}'
        if k in st and st[k]['std'] > 0:
            X[:, j] = np.clip(X[:, j], st[k]['low'], st[k]['high'])
            X[:, j] = (X[:, j] - st[k]['mean']) / st[k]['std']
    return np.nan_to_num(X, nan=0.0)

conn = get_tushare_db()
st = sqlite3.connect(str(BASE / 'signals.db'))
sig = st.execute("select max(replace(date,'-','')) from signal_history").fetchone()[0]
print('信号日:', sig, flush=True)
# 修(0927): 首建期表不存在时跳过"已入库"去重(建表语句在后面IF NOT EXISTS兜底)
try:
    have = {r[0] for r in st.execute("select distinct date from shadow_v10d_v5_scores").fetchall()}
except sqlite3.OperationalError:
    have = set()
if sig in have and os.environ.get('FORCE') != '1':
    print('当日已有，退出'); sys.exit(0)

stocks = [r[0] for r in conn.execute(
    "SELECT symbol FROM stock_basic WHERE market != '北交所' AND (name NOT LIKE '%ST%' OR name IS NULL) "
    "AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%' AND symbol NOT LIKE '92%'").fetchall()]
idx_data = load_index_data()

rows10, rows20, rows40 = [], [], []
t0 = time.time()
for ci, code in enumerate(stocks):
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code}' AND trade_date <= '{sig}'
        ORDER BY trade_date DESC LIMIT 200""").fetchall()
    if len(rows) < 120: continue
    rows = rows[::-1]
    closes = [float(r[1]) for r in rows]; highs = [float(r[3]) for r in rows]
    lows = [float(r[4]) for r in rows]; pcts = [float(r[5])/100.0 for r in rows]
    vols = [float(r[6]) for r in rows]
    dates = [str(r[0])[:10] if '-' in str(r[0]) else f'{str(r[0])[:4]}-{str(r[0])[4:6]}-{str(r[0])[6:8]}' for r in rows]
    if dates[-1].replace('-','') != sig: continue
    adj_rows = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts_code]).fetchall()
    ac, ah, al = apply_forward_adjust(closes, highs, lows, adj_rows)
    board_idx = get_board_index(code)
    idx_info = idx_data.get(board_idx)
    idx_closes = None
    if idx_info:
        import bisect
        # 修(0927): 与core/scoring.py 0926修复同口径 — idx日期带横杠须去横杠比对; 返回dict(旧版list+恒False判据致ex列恒0)
        _q = dates[-1].replace('-','')
        _dn = [dd.replace('-','') for dd in idx_info['dates']]
        ip = bisect.bisect_right(_dn, _q) - 1
        if ip >= 20:
            idx_closes = {idx_info['dates'][j]: idx_info['dict'][idx_info['dates'][j]] for j in range(ip + 1)}
    val_row = conn.execute(
        "SELECT pe_ttm, pb, total_mv FROM daily_basic WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
        [ts_code, sig]).fetchone()
    val_dict = {}
    if val_row:
        pe, pb, mv = val_row
        if pe and float(pe) > 0: val_dict['ep'] = 1.0/float(pe)
        if pb and float(pb) > 0: val_dict['bp'] = 1.0/float(pb)
        if mv and float(mv) > 0: val_dict['ln_cap'] = np.log(float(mv))
    feat38 = compute_features(ac, ah, al, vols, pcts, idx_closes, val_dict)
    if feat38 is None: continue
    f31 = np.array([feat38[j] for j in PV_INDICES], dtype=float).reshape(1, -1)
    f31s = standardize(f31, s10)
    rows10.append([sig, code, float(m10.predict(f31s)[0])])
    f31s2 = standardize(f31, s20)
    rows20.append([sig, code, float(m20.predict(f31s2)[0])])
    # 29维含因子（40d增量口径，与 core/scoring.py _compute_ml_features 一致）
    fv = get_factor_from_db(code, sig, FACTOR_FIELDS, conn)
    fac = [float(fv.get(f, 0.0)) for f in FACTOR_FIELDS]
    f29 = np.append(np.array([feat38[j] for j in BASE_KEEP], dtype=float), np.array(fac, dtype=float)).reshape(1, -1)
    f29s = standardize(f29, s40)
    rows40.append([sig, code, float(m40.predict(f29s)[0])])
    if (ci+1) % 500 == 0:
        print(f'  {ci+1}/{len(stocks)} {time.time()-t0:.0f}s', flush=True)
conn.close()

for tbl, rows in [('shadow_v10d_v5_scores', rows10), ('shadow_v20d_v2_scores', rows20), ('shadow_v40d_inc_scores', rows40)]:
    st.execute(f"CREATE TABLE IF NOT EXISTS {tbl}(date TEXT, code TEXT, score DOUBLE, PRIMARY KEY(date, code))")
    st.executemany(f"INSERT OR REPLACE INTO {tbl} VALUES (?,?,?)", rows)
st.commit()
print(f'完成: {len(rows10)} 票 ×3 表  {time.time()-t0:.0f}s')
