#!/usr/bin/env python3
"""影子链对拍验证：Mac 复刻管线算的特征+stats变换+model_B_final
vs ab_samples.parquet 里同日期样本经 stats 变换后 model_B_final 的预测。
秩相关应 ≈1.0，否则 Mac 侧管线与训练管线没对齐，影子分不可信。"""
import sys, json, sqlite3
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE / 'scripts')); sys.path.insert(0, str(BASE))
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
from core.db import get_tushare_db

FEAT_WIN = 60
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
FEAT_NAMES = ['chg5','chg10','chg20','chg60','d5','d10','d20','bull1','bull2',
              'rr','std20','vr','pos','nh','vpc','c1d','c3d','ex5','ex10','ex20',
              'skew20','kurt20','dn_streak','up_ratio10','vol_chg','kurt60',
              'slope5','slope10','accel','vp_shrink','vp_div']
TDX_FEATS = ['open30_ret','tail30_ret','vwap_dev','rv_1m','amp_intra',
             'vol_dist_am','vol_dist_tail','tail5_ret','last_vol_share']
COLS = FEAT_NAMES + TDX_FEATS

TARGET = '20260521'   # 训练样本窗内的日期
meta = json.loads((BASE / 'models/shadow/stats_B.json').read_text())
model = lgb.Booster(model_file=str(BASE / 'models/shadow/model_B_final.txt'))

# ---- 参照：parquet 样本 -> stats 变换 -> 模型预测
df = pd.read_parquet(BASE / 'analysis/ab_intraday/ab_samples.parquet')
sub = df[df['date'] == TARGET].reset_index(drop=True)
Xp = sub[COLS].to_numpy(dtype=np.float64).copy()
for st in meta['stats']:
    j = COLS.index(st['col'])
    Xp[:, j] = (np.clip(Xp[:, j], st['lo'], st['hi']) - st['mean']) / (st['std'] or 1.0)
ref_pred = model.predict(np.nan_to_num(Xp))
ref = dict(zip(sub['code'], ref_pred))
print(f'参照样本 {len(sub)} 股 (parquet {TARGET})')

# ---- Mac 影子管线重算该日特征（与 shadow_score_daily.py 同逻辑）
conn = get_tushare_db()
idx_data = load_index_data()
tcon = sqlite3.connect(f"file:{BASE}/signals.db?mode=ro", uri=True)
tdx_row = pd.read_sql_query(
    f"SELECT code, {','.join(TDX_FEATS)} FROM tdx_intraday_feat WHERE date={TARGET}", tcon)
tdx_map = tdx_row.set_index('code')
cut = conn.execute(
    f"SELECT MIN(trade_date) FROM (SELECT DISTINCT trade_date FROM daily "
    f"WHERE trade_date <= '{TARGET}' ORDER BY trade_date DESC LIMIT 110)").fetchone()[0]
stocks = sorted(ref.keys())  # 只对参照里的股票重算，逐一对齐
rows, codes = [], []
for code in stocks:
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    dfr = conn.execute(
        "SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol FROM daily "
        f"WHERE ts_code='{ts_code}' AND trade_date >= '{cut}' AND trade_date <= '{TARGET}' ORDER BY trade_date").fetchall()
    closes = [float(r[1]) for r in dfr]; highs = [float(r[2]) for r in dfr]
    lows = [float(r[3]) for r in dfr]
    pcts = [float(r[4])/100.0 for r in dfr]; vols = [float(r[5]) for r in dfr]
    dates = [str(r[0])[:10] for r in dfr]
    adj_rows = conn.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",
        [ts_code]).fetchall()
    ac, ah, al = apply_forward_adjust(closes, highs, lows, adj_rows)
    idx_info = idx_data.get(get_board_index(code))
    idx_dict = None
    if idx_info and dates[-1] in idx_info.get('dict', {}):
        idx_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates[-1]}
    f38 = compute_features(ac[-FEAT_WIN-1:], ah[-FEAT_WIN-1:], al[-FEAT_WIN-1:],
                           vols[-FEAT_WIN-1:], pcts[-FEAT_WIN-1:], idx_dict,
                           {'ep':0.5,'bp':0.5,'ln_cap':22.0})
    tr = tdx_map.loc[code]
    rows.append([f38[j] for j in PV_INDICES] + [float(tr[k]) for k in TDX_FEATS])
    codes.append(code)

X = np.array(rows, dtype=np.float64)
for st in meta['stats']:
    j = COLS.index(st['col'])
    X[:, j] = (np.clip(X[:, j], st['lo'], st['hi']) - st['mean']) / (st['std'] or 1.0)
mac_pred = model.predict(np.nan_to_num(X))

common = [(c, p) for c, p in zip(codes, mac_pred) if c in ref]
mc = np.array([p for _, p in common]); rc = np.array([ref[c] for c, _ in common])
rho = stats.spearmanr(mc, rc)[0]
mad = np.abs(mc - rc).mean(); mx = np.abs(mc - rc).max()
print(f'重叠 {len(common)} 股  秩相关 {rho:.6f}  绝对差 mean {mad:.2e} max {mx:.2e}')
print('判定:', 'PASS 管线对齐' if rho > 0.999 and mx < 1e-3 else 'FAIL 管线未对齐')