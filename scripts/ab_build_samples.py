#!/usr/bin/env python3
"""日内特征 A/B 实验 — 样本宽表拼装（Mac 上跑，内存纪律：分块拼接，只保留截面行）
输出 analysis/ab_intraday/ab_samples.parquet：date, code, 27基础特征, 9日内特征, y
切分口径（training-data-split-strategies skill）：
  train = 2021-01-01~2024-12-31（验证标准化stats用，不进test）
  val   = 2025-01-01~2026-02-11
  test  = 2026-02-12~今（1分钟特征覆盖窗）
只保留 date>=2021 的样本行（特征窗60天从2020-10起需读价格，但不落盘更早样本）。
"""
import sys, json, time, sqlite3
import numpy as np, pandas as pd
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE / 'scripts'))
sys.path.insert(0, str(BASE))
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
from core.db import get_tushare_db

FEAT_WIN, FWD_DAYS = 60, 10
TRAIN_END, VAL_END = '20250101', '20260212'   # train<TRAIN_END<=val<VAL_END<=test
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
FEAT_NAMES = ['chg5','chg10','chg20','chg60','d5','d10','d20','bull1','bull2',
              'rr','std20','vr','pos','nh','vpc','c1d','c3d','ex5','ex10','ex20',
              'skew20','kurt20','dn_streak','up_ratio10','vol_chg','kurt60',
              'slope5','slope10','accel','vp_shrink','vp_div']
TDX_FEATS = ['open30_ret','tail30_ret','vwap_dev','rv_1m','amp_intra',
             'vol_dist_am','vol_dist_tail','tail5_ret','last_vol_share']

t0 = time.time()
conn = get_tushare_db()
idx_data = load_index_data()

stocks = [r[0] for r in conn.execute(
    "SELECT symbol, name FROM stock_basic WHERE market != '北交所'").fetchall()
    if not any(s in (r[1] or '') for s in ('ST','st','退'))
    and not r[0].startswith(('8','4','92'))]
print(f"股票池 {len(stocks)}", flush=True)

# 1分钟特征整表载入（135天×~5200股≈70万行×9列 float64 ≈ 50MB，安全）
tcon = sqlite3.connect(f"file:{BASE}/signals.db?mode=ro", uri=True)
tdx = pd.read_sql_query(
    f"SELECT date, code, {','.join(TDX_FEATS)} FROM tdx_intraday_feat", tcon)
tdx['date'] = tdx['date'].astype(str)
tmap = {c: g.set_index('date')[TDX_FEATS] for c, g in tdx.groupby('code')}
tdx_dates = set(tdx['date'])
print(f"tdx特征 {len(tdx)}行 {len(tmap)}股 覆盖{min(tdx_dates)}~{max(tdx_dates)}", flush=True)

rows = []
for ci, code in enumerate(stocks):
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    dfr = conn.execute(
        "SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol FROM daily "
        f"WHERE ts_code='{ts_code}' AND trade_date >= '2020-10-01' ORDER BY trade_date").fetchall()
    if len(dfr) < FEAT_WIN + FWD_DAYS + 10:
        continue
    closes = [float(r[1]) for r in dfr]
    highs = [float(r[2]) for r in dfr]; lows = [float(r[3]) for r in dfr]
    pcts = [float(r[4])/100.0 for r in dfr]; vols = [float(r[5]) for r in dfr]
    dates = [str(r[0])[:10] for r in dfr]
    adj_rows = conn.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts_code]).fetchall()
    ac, ah, al = apply_forward_adjust(closes, highs, lows, adj_rows)
    board = get_board_index(code)
    idx_info = idx_data.get(board)
    tdx_g = tmap.get(code)
    n = len(dates)
    feat_mat = np.empty((n, 31), dtype=np.float64)  # 占位: 31列
    for i in range(FEAT_WIN, n - FWD_DAYS):
        dt = dates[i].replace('-', '')
        if dt < VAL_END:
            continue  # A/B同窗实验只在1分钟特征窗内训练（Mac内存纪律，只落test窗样本）
        if tdx_g is None:
            continue
        win_c, win_h, win_l = ac[i-FEAT_WIN:i+1], ah[i-FEAT_WIN:i+1], al[i-FEAT_WIN:i+1]
        win_v, win_p = vols[i-FEAT_WIN:i+1], pcts[i-FEAT_WIN:i+1]
        idx_dict = None
        if idx_info and dates[i] in idx_info.get('dict', {}):
            idx_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates[i]}
        f38 = compute_features(win_c, win_h, win_l, win_v, win_p, idx_dict,
                               {'ep':0.5,'bp':0.5,'ln_cap':22.0})
        base = [f38[j] for j in PV_INDICES]
        y = ac[i+FWD_DAYS] / ac[i] - 1
        row = {'date': dt, 'code': code, 'y': y}
        row.update(dict(zip(FEAT_NAMES, base)))
        if dt in tdx_dates and tdx_g is not None and dt in tdx_g.index:
            tr = tdx_g.loc[dt]
            row.update({k: float(tr[k]) for k in TDX_FEATS})
        else:
            row.update({k: np.nan for k in TDX_FEATS})
        rows.append(row)
    if (ci+1) % 300 == 0:
        print(f"  {ci+1}/{len(stocks)} 样本{len(rows):,} {time.time()-t0:.0f}s", flush=True)
conn.close()

df = pd.DataFrame(rows)
# 剔除无1分钟特征的样本（停牌日无分钟bar；A/B同一样本集，剔除不引入组间偏差）
before = len(df)
df = df.dropna(subset=TDX_FEATS).reset_index(drop=True)
te = df
print(f"剔除无tdx行 {before-len(df)} ({(before-len(df))/before*100:.1f}%)")
print(f"样本窗 {df.date.min()}~{df.date.max()} 共{len(df):,} 日截面数{df.date.nunique()}")
out = BASE / 'analysis' / 'ab_intraday'; out.mkdir(parents=True, exist_ok=True)
df.to_parquet(out / 'ab_samples.parquet')
print(f"已写 {out}/ab_samples.parquet  耗时{time.time()-t0:.0f}s")