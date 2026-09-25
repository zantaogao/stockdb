# -*- coding: utf-8 -*-
"""分钟微观特征·单日计算库（v4e 影子链用，2026-09-06）
口径与 _build_minfeat_0906.py 逐字一致（训练即此口径）：
  f50 intraday maxdd（5min累计log收益最大回撤，负数）
  f51 vol_burst（单bar最大量/日总量）
  f52 downside_var（负收益方差占比）
  f53 kyle_illiq（mean(|r|/max(vol*close,1))*1e8）
数据源 minutes/5min/{mkt}_{code}.parquet（不复权），time=YYYYMMDDHHMMSS000。
"""
import os
import numpy as np
import pandas as pd
from multiprocessing import Pool

BASE = os.path.expanduser('~/.hermes/stockdb')
MIN = BASE + '/minutes/5min'
NEW4 = ['f50_intraday_dd', 'f51_vol_burst', 'f52_downside_var', 'f53_kyle_illiq']


def _compute_one(args):
    code6, target = args   # target: 'YYYY-MM-DD'
    mkt = 'sh' if code6[0] in '66895' else 'sz'
    f = f'{MIN}/{mkt}_{code6}.parquet'
    if not os.path.exists(f):
        f = f'{MIN}/sz_{code6}.parquet'   # 同 _build_minfeat_0906 回退口径
    if not os.path.exists(f):
        return None
    try:
        d = pd.read_parquet(f)
    except Exception:
        return None
    if d['date'].astype(str).max() < target:      # 无目标日分钟数据
        return None
    d = d[d['date'].astype(str) == target].sort_values('time')
    if len(d) < 10:
        return None
    c = d['close'].values.astype(float); v = d['volume'].values.astype(float)
    lg = np.zeros(len(c))
    ok = (c[:-1] > 0) & (c[1:] > 0)
    lg[1:] = np.where(ok, np.log(np.where(ok, c[1:] / np.maximum(c[:-1], 1e-9), 1.0)), 0.0)
    amt = np.maximum(v * np.clip(c, 0.01, None), 1.0)
    cum = np.cumsum(np.where(np.isfinite(lg), lg, 0.0))
    peak = np.maximum.accumulate(cum)
    f50 = float(-(peak - cum).max())
    tot = v.sum()
    f51 = float(v.max() / tot) if tot > 0 else np.nan
    neg_sq = np.square(np.where(lg < 0, lg, 0.0)).sum()
    pos_sq = np.square(np.where(lg > 0, lg, 0.0)).sum()
    f52 = float(neg_sq / (neg_sq + pos_sq)) if (neg_sq + pos_sq) > 0 else np.nan
    f53 = float((np.abs(lg) / amt).mean() * 1e8)
    return (code6, f50, f51, f52, f53)


def min_feats_for_date(target_compact, workers=8):
    """target_compact: 'YYYYMMDD'。返回 DataFrame(code, f50..f53)；票数<100 视为分钟数据未到位返回空。"""
    target = f'{target_compact[:4]}-{target_compact[4:6]}-{target_compact[6:]}'
    codes = sorted(fn[3:9] for fn in os.listdir(MIN) if fn.endswith('.parquet'))
    with Pool(workers) as p:
        res = [r for r in p.map(_compute_one, [(c, target) for c in codes], chunksize=8) if r]
    df = pd.DataFrame(res, columns=['code'] + NEW4)
    return df if len(df) >= 100 else df.iloc[0:0]