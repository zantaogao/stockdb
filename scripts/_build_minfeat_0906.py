# 第三批·日内微观结构特征 f47-f56（2026-09-06）
# 数据源：minutes/5min/{mkt}_{code}.parquet（baostock 5min，2025-04-08起，不复权）
# 输出：analysis/retrain_10d_v4/_min_feats.parquet  (date,code,f47..f56)
# 纪律：只用于 date>=2025-04-08 重叠段；v4e vs v4d 对拍限定同样本
import os, time
import numpy as np
import pandas as pd
from multiprocessing import Pool

BASE = os.path.expanduser('~/.hermes/stockdb')
MIN  = BASE + '/minutes/5min'
OUT  = BASE + '/analysis/retrain_10d_v4/_min_feats.parquet'

def compute_one(code6):
    """返回该票全部交易日的 f47-f56；找不到文件返回 (code6, None)"""
    mkt = 'sh' if code6[0] in '66895' else 'sz'
    f = f'{MIN}/{mkt}_{code6}.parquet'
    if not os.path.exists(f):
        f = f'{MIN}/sz_{code6}.parquet'
        if not os.path.exists(f):
            return code6, None
    try:
        d = pd.read_parquet(f, columns=['date','time','high','low','close','volume'])
    except Exception:
        return code6, None
    d = d.sort_values('time')
    hh = d['time'].str.slice(8, 12).astype(int)   # HHMM（time是17位：YYYYMMDD+HHMMSS+000，HHMM在下标8-11）
    c = d['close'].values; v = d['volume'].values.astype(float)
    lg = np.zeros(len(c))
    lg[1:] = np.log(np.where(c[1:] > 0, c[1:], np.nan) / np.where(c[:-1] > 0, c[:-1], np.nan))
    # 跨日边界处的bar收益置0（每日首bar收益另算无意义）
    newday = np.concatenate([[True], (d['date'].values[1:] != d['date'].values[:-1])])
    lg[newday] = 0.0
    d = d.assign(
        lg=lg,
        am_ret_c=np.where(hh < 1200, lg, 0.0),
        pm_ret_c=np.where(hh >= 1300, lg, 0.0),
        tail_v=np.where(hh >= 1430, v, 0.0),
        neg_sq=np.square(np.where(lg < 0, lg, 0.0)),
        pos_sq=np.square(np.where(lg > 0, lg, 0.0)),
    )
    g = d.groupby('date', sort=True)
    agg = g.agg(
        am_ret=('am_ret_c','sum'),
        pm_ret=('pm_ret_c','sum'),
        tot_v=('volume','sum'),
        tail_v=('tail_v','sum'),
        last_c=('close','last'),
        day_l=('low','min'), day_h=('high','max'),
        max_bar=('volume','max'),
        var_neg=('neg_sq','sum'),
        var_pos=('pos_sq','sum'),
        sum_lg=('lg','sum'),
    )
    # top3 bar量占比、pvcorr、vwap穿越需要逐组apply，但48行/组×350组可接受
    extra = g.apply(lambda x: _group_extra(x['close'].values, x['volume'].values.astype(float), x['lg'].values), include_groups=False)
    agg = agg.join(pd.DataFrame(extra.tolist(), index=agg.index))
    # f53 illiq 用5min |r|/金额，金额没读进来——用 volume*close 近似成交额
    amt = (d['volume'].values.astype(float) * np.clip(d['close'].values, 0.01, None))
    d2 = d.assign(illiq=np.abs(d['lg'].values) / np.maximum(amt, 1.0) * 1e8)
    agg['illiq1'] = d2.groupby('date')['illiq'].mean()
    agg = agg.sort_index()
    agg['f47'] = agg['pm_ret'] - agg['am_ret']
    agg['f48'] = agg['tail_v'] / agg['tot_v'].replace(0, np.nan)
    lo, hi, lc = agg['day_l'], agg['day_h'], agg['last_c']
    agg['f49'] = ((lc - lo) / (hi - lo).replace(0, np.nan)).clip(-0.5, 1.5)
    agg['f51'] = agg['max_bar'] / agg['tot_v'].replace(0, np.nan)
    tv = agg['var_neg'] + agg['var_pos']
    agg['f52'] = agg['var_neg'] / tv.replace(0, np.nan)
    agg['f53'] = agg['illiq1']
    # f50 intraday maxdd：日内累计lg的最大回撤，逐日48bar python循环
    dd = g['lg'].apply(lambda x: _maxdd(x.values))
    agg['f50'] = dd
    # f54 top3bar占比、f55 pv_corr、f56 vwap穿越 已在 extra: top3_share, pvcorr, cross_n
    agg['f54'] = agg['top3_share']; agg['f55'] = agg['pvcorr']; agg['f56'] = agg['cross_n']
    out = agg.reset_index()[['date','f47','f48','f49','f50','f51','f52','f53','f54','f55','f56']]
    out['code'] = code6
    return code6, out

def _maxdd(x):
    cum = np.cumsum(np.where(np.isfinite(x), x, 0.0))
    peak = np.maximum.accumulate(cum)
    return float(-(peak - cum).max())  # 负数，越深越负

def _group_extra(close, vol, lg):
    n = len(close)
    if n < 10 or vol.sum() <= 0:
        return {'top3_share': np.nan, 'pvcorr': np.nan, 'cross_n': np.nan}
    s = np.sort(vol)
    top3 = s[-3:].sum() / vol.sum()
    if vol.std() > 0 and np.std(lg) > 0:
        pv = float(np.corrcoef(lg, vol)[0, 1])
    else:
        pv = np.nan
    vwap = np.cumsum(close * vol) / np.maximum(np.cumsum(vol), 1e-9)
    dev = close - vwap
    sgn = np.sign(dev); sgn[sgn == 0] = 1
    cross = int((sgn[1:] != sgn[:-1]).sum())
    return {'top3_share': float(top3), 'pvcorr': pv, 'cross_n': float(cross)}

def main():
    t0 = time.time()
    sm = pd.read_parquet(BASE + '/analysis/retrain_10d_v4/samples_v4c.parquet', columns=['date','code'])
    codes = sorted(sm['code'].unique())
    print(f'样本票数: {len(codes)}', flush=True)
    res = []
    with Pool(8) as p:
        for i, (code, df) in enumerate(p.imap_unordered(compute_one, codes, chunksize=8)):
            if df is not None and len(df):
                res.append(df)
            if (i + 1) % 500 == 0:
                print(f'[{i+1}/{len(codes)}] {time.time()-t0:.0f}s', flush=True)
    allf = pd.concat(res, ignore_index=True)
    allf['date'] = allf['date'].astype(str)
    allf.to_parquet(OUT, index=False)
    print(f'完成 {time.time()-t0:.0f}s rows={len(allf)} → {OUT}', flush=True)

if __name__ == '__main__':
    main()