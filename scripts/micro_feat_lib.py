# -*- coding: utf-8 -*-
"""日频微观特征·单日计算库（v4f 影子链用，2026-09-20 上线）
口径与 _microstructure_ic_0919.py（发现轮）逐字一致（训练即此口径）：
  volume>0 过滤 → barret = close.pct_change()
  kyle   = mean(|barret| / (volume + 1) * 1e8)
  amihud = mean(|barret| / (amount + 1) * 1e10)
数据源 minutes/5min/{mkt}_{code}.parquet（不复权），date 列 = 'YYYY-MM-DD'。
注意：与 min_feat_lib 的 f53_kyle_illiq 不是同一口径（f53 用 log收益/(vol*close)），
v4f 必须用本库，勿混。
"""
import os
import numpy as np
import pandas as pd
from multiprocessing import Pool

BASE = os.path.expanduser('~/.hermes/stockdb')
MIN = BASE + '/minutes/5min'
MICRO2 = ['kyle', 'amihud']


def _compute_one(args):
    code6, target = args   # target: 'YYYY-MM-DD'
    f = f'{MIN}/sh_{code6}.parquet'
    if not os.path.exists(f):
        f = f'{MIN}/sz_{code6}.parquet'
    if not os.path.exists(f):
        return None
    try:
        d = pd.read_parquet(f, columns=['date', 'close', 'volume', 'amount'])
    except Exception:
        return None
    if d['date'].astype(str).max() < target:      # 无目标日分钟数据
        return None
    # 口径逐字照抄发现轮 _microstructure_ic_0919：先全表 volume>0 过滤 + 全表 pct_change
    # （当日首bar收益=前日末bar收盘→当日首bar，跨日连算），再切目标日求均值。
    # 勿改成"切片内pct_change"——首bar差一个跨日收益，5170票里96%会对不上训练口径。
    d = d[d['volume'] > 0]
    barret = d['close'].astype(float).pct_change()
    day_mask = d['date'].astype(str) == target
    barret = barret[day_mask.to_numpy()].to_numpy(dtype=float)
    vol = d['volume'].to_numpy(dtype=float)[day_mask.to_numpy()]
    amt = d['amount'].to_numpy(dtype=float)[day_mask.to_numpy()]
    if len(vol) < 10:
        return None
    ok = np.isfinite(barret)
    if ok.sum() < 5:
        return None
    kyle = float(np.mean(np.abs(barret[ok]) / (vol[ok] + 1) * 1e8))
    amihud = float(np.mean(np.abs(barret[ok]) / (amt[ok] + 1) * 1e10))
    if not (np.isfinite(kyle) and np.isfinite(amihud)):
        return None
    return (code6, kyle, amihud)


def micro_feats_for_date(target_compact, workers=8):
    """target_compact: 'YYYYMMDD'（同 min_feat_lib 入口口径）。返回 DataFrame(code, kyle, amihud)；
    票数<100 视为分钟数据未到位返回空。"""
    target = f'{target_compact[:4]}-{target_compact[4:6]}-{target_compact[6:]}'
    codes = sorted(fn[3:9] for fn in os.listdir(MIN) if fn.endswith('.parquet'))
    with Pool(workers) as p:
        res = [r for r in p.map(_compute_one, [(c, target) for c in codes], chunksize=8) if r]
    df = pd.DataFrame(res, columns=['code'] + MICRO2)
    return df if len(df) >= 100 else df.iloc[0:0]
