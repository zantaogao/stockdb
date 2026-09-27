"""三链样本构建 v8（2026-09-27 用户拍板：训练样本统一 2019 起）
基于 scripts/_cron_retrain_build_0926.py，改动：
  1. SAMPLE_START='20190101'，股票窗口查询多回看320天（60窗口暖机+20预热）
  2. ex5/10/20 走 compute_features 新口径（个股日历回看，dates 必传）
  3. 日历行过滤 di<20 用全量日历（2019年起始行自动满足）
  4. F40_START='20190101'（40d 不再限 2026 起）
  5. 20d 样本行不依赖 i+20 有 y（同 0926）
输出 analysis/retrain_20260927_v8/samples_{10d,20d,40d}.parquet
  10d/20d: (date, code, f0..f30, y10|y20)  date=YYYYMMDD
  40d: (date, code, f0..f25, f31,f32,f33, y40)
"""
import sys, time
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path.home() / '.hermes/stockdb'
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / 'scripts'))
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data

FEAT_WIN = 60
SAMPLE_START = '20190101'
LOOKBACK = '20180201'   # 股票窗口回看起点（60窗口暖机+20预热）
F40_START = '20190101'
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
BASE_KEEP = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
OUT = BASE / 'analysis/retrain_20260927_v8'
OUT.mkdir(exist_ok=True)
FC10 = ['f%d' % j for j in range(31)]
FC40 = ['f%d' % j for j in range(26)] + ['f31', 'f32', 'f33']

conn = get_tushare_db()
stocks = [r[0] for r in conn.execute(
    "SELECT symbol FROM stock_basic WHERE market != '北交所' AND (name NOT LIKE '%ST%' OR name IS NULL) "
    "AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%' AND symbol NOT LIKE '92%'").fetchall()]
print(f'股票池: {len(stocks)}', flush=True)

cal = [str(r[0]) for r in conn.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE trade_date >= ? ORDER BY 1", ['20180201']).fetchall()]
cal_idx = {d: i for i, d in enumerate(cal)}
idx_data = load_index_data()
print(f'日历: {len(cal)}天  {cal[0]} ~ {cal[-1]}', flush=True)

t0 = time.time()
db_rows = conn.execute(
    "SELECT ts_code, trade_date, pe_ttm, pb, total_mv FROM daily_basic WHERE trade_date >= ? ORDER BY ts_code, trade_date",
    [SAMPLE_START]).fetchall()
val_by_code = {}
for ts, d, pe, pb, mv in db_rows:
    vd = {}
    if pe is not None and float(pe) > 0: vd['ep'] = 1.0 / float(pe)
    if pb is not None and float(pb) > 0: vd['bp'] = 1.0 / float(pb)
    if mv is not None and float(mv) > 0: vd['ln_cap'] = np.log(float(mv))
    val_by_code.setdefault(ts, {})[str(d)] = vd
print(f'daily_basic 载入 {len(db_rows):,} 行 {time.time()-t0:.0f}s', flush=True)

sf_rows = conn.execute(
    "SELECT ts_code, trade_date, kdj_k, cci, rsi_12 FROM stk_factor WHERE trade_date >= ? ORDER BY ts_code, trade_date",
    [SAMPLE_START]).fetchall()
fac_by_code = {}
for ts, d, k, c, r in sf_rows:
    fac_by_code.setdefault(ts, {})[str(d)] = [
        float(k) if k is not None else 0.0,
        float(c) if c is not None else 0.0,
        float(r) if r is not None else 0.0]
print(f'stk_factor 载入 {len(sf_rows):,} 行 {time.time()-t0:.0f}s', flush=True)

rows10, rows20, rows40 = [], [], []
batch_i = 0
(OUT / 'batches').mkdir(exist_ok=True)
t0 = time.time(); miss_val = 0; bad_feat = 0

def flush(force=False):
    global rows10, rows20, rows40, batch_i
    if len(rows10) < 50000 and not force: return
    for tbl, rows, cols in [('10d', rows10, ['date','code']+FC10+['y10']),
                            ('20d', rows20, ['date','code']+FC10+['y20']),
                            ('40d', rows40, ['date','code']+FC40+['y40'])]:
        if not rows: continue
        df = pd.DataFrame(rows, columns=cols)
        df.to_parquet(OUT / f'batches/{tbl}_b{batch_i:03d}.parquet', index=False)
    batch_i += 1
    print(f'  FLUSH 10d={len(rows10):,} 20d={len(rows20):,} 40d={len(rows40):,}  {time.time()-t0:.0f}s', flush=True)
    rows10, rows20, rows40 = [], [], []

dash = lambda x: f'{x[:4]}-{x[4:6]}-{x[6:8]}' if '-' not in str(x) else str(x)

for ci, code in enumerate(stocks):
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code}' AND trade_date >= '{LOOKBACK}' ORDER BY trade_date
    """).fetchall()
    if len(rows) < FEAT_WIN + 11: continue
    closes = [float(r[1]) for r in rows]; highs_raw = [float(r[3]) for r in rows]
    lows_raw = [float(r[4]) for r in rows]; pcts = [float(r[5])/100.0 for r in rows]
    volumes = [float(r[6]) for r in rows]; dates = [str(r[0]) for r in rows]

    adj_rows = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts_code]).fetchall()
    adj_closes, adj_highs, adj_lows = apply_forward_adjust(closes, highs_raw, lows_raw, adj_rows)
    board_idx = get_board_index(code); idx_info = idx_data.get(board_idx)

    lab = {str(r[0]): float(r[1]) for r in conn.execute(
        f"SELECT trade_date, close FROM daily WHERE ts_code='{ts_code}' AND trade_date >= '{LOOKBACK}'").fetchall()}
    vmap = val_by_code.get(ts_code, {})
    fmap = fac_by_code.get(ts_code, {})

    for i in range(FEAT_WIN, len(rows) - 10):
        d = dates[i]
        if d < SAMPLE_START: continue
        di = cal_idx.get(d)
        if di is None or di < 20: continue
        idx_closes = None
        if idx_info:
            idx_closes = {dd: idx_info['dict'][dd] for dd in sorted(idx_info['dict']) if dd <= d}
            if len(idx_closes) < 20: idx_closes = None
        val_dict = vmap.get(d)
        if val_dict is None:
            miss_val += 1
            val_dict = {}

        win_dates = [dash(x) for x in dates[i-FEAT_WIN:i+1]]
        feat_38 = compute_features(adj_closes[i-FEAT_WIN:i+1], adj_highs[i-FEAT_WIN:i+1], adj_lows[i-FEAT_WIN:i+1],
                                   volumes[i-FEAT_WIN:i+1], pcts[i-FEAT_WIN:i+1], idx_closes, val_dict, dates=win_dates)
        if feat_38 is None: continue
        feat_38 = list(feat_38)
        if len(feat_38) != 38:
            bad_feat += 1
            print(f'BAD_LEN code={code} date={d} len={len(feat_38)}', flush=True)
            continue
        base = adj_closes[i]
        f31 = [float(feat_38[j]) for j in PV_INDICES]

        c10 = lab.get(dates[i + 10])
        if c10 is None or base <= 0: continue
        rows10.append((d, code, *f31, (c10 / base - 1) * 100))
        if i + 20 < len(dates):
            c20 = lab.get(dates[i + 20])
            if c20 is not None:
                rows20.append((d, code, *f31, (c20 / base - 1) * 100))
        if d >= F40_START and i + 40 < len(dates):
            c40 = lab.get(dates[i + 40])
            if c40 is not None:
                keep26 = [float(feat_38[j]) for j in BASE_KEEP]
                rows40.append((d, code, *(keep26 + fmap.get(d, [0.0, 0.0, 0.0])), (c40 / base - 1) * 100))

    if (ci + 1) % 200 == 0:
        flush()
        print(f'  {ci+1}/{len(stocks)}  {time.time()-t0:.0f}s  缺估值{miss_val} 坏特征{bad_feat}', flush=True)

flush(force=True)
conn.close()
# 汇总分片 → 最终文件（按 date,code 去重保首现）
for k, cols in [('10d', ['date','code']+FC10+['y10']), ('20d', ['date','code']+FC10+['y20']), ('40d', ['date','code']+FC40+['y40'])]:
    parts = sorted((OUT / 'batches').glob(f'{k}_b*.parquet'))
    if not parts:
        print(f'{k}: 无分片'); continue
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = df.drop_duplicates(subset=['date','code'], keep='first')
    df.to_parquet(OUT / f'samples_{k}.parquet', index=False)
    print(f'{k}: {len(df):,} 行 {df.date.min()}~{df.date.max()}', flush=True)
print('BUILD_DONE', flush=True)
