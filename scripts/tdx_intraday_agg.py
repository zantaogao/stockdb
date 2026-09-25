#!/usr/bin/env python3
"""TDX 分钟线 → 日频特征聚合（2026-08-08 新增）
数据: ~/.hermes/stockdb/tdx/vipdoc/{sh,sz}/{minline,*.lc1}
输出: signals.db 表 tdx_intraday_feat (每天每只 1 行)
特征: open30_ret/tail30_ret/vwap_dev/rv_1m/amp_intra/vol_dist_am/gap_ret
用法: python3 -B scripts/tdx_intraday_agg.py [YYYYMMDD]  (默认全量)
"""
import numpy as np, pandas as pd, sqlite3, sys, os, glob
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TDX = BASE / 'tdx' / 'vipdoc'
STATE_DB = BASE / 'signals.db'  # v2温层: tdx_intraday_feat

# 通达信 1 分钟线 32 字节记录（最后 4 字节为 padding/未知字段，必须占位否则错位）
DT = np.dtype([('date', 'u2'), ('time', 'u2'), ('open', 'f4'), ('high', 'f4'),
               ('low', 'f4'), ('close', 'f4'), ('vol', 'f4'), ('amount', 'f4'),
               ('_pad', 'u4')])

def decode_date(v):
    v = v.astype(np.int64)
    year = v // 2048 + 2004
    rest = v % 2048
    return year * 10000 + (rest // 100) * 100 + (rest % 100)

def parse_lc1(fn):
    """解析单文件 → DataFrame[date(YYYYMMDD), t(分钟), open, high, low, close, vol]"""
    if os.path.getsize(fn) == 0:
        return pd.DataFrame()
    a = np.fromfile(fn, dtype=DT)
    if len(a) < 10:
        return pd.DataFrame()
    d = pd.DataFrame({
        'date': decode_date(a['date']),
        't': a['time'].astype(int),
        'open': a['open'], 'high': a['high'], 'low': a['low'],
        'close': a['close'], 'vol': a['vol'].astype(np.float64),
    })
    # 时间 → 分钟数（09:31 = 571）
    d['tm'] = d['t'] // 60 * 60 + d['t'] % 60
    d = d[(d['tm'] >= 9 * 60 + 31) & (d['tm'] <= 15 * 60)].copy()
    return d

def agg_day(df):
    """单股票聚合日频特征"""
    if df.empty or len(df) < 100:
        return None
    d0 = df['date'].iloc[0]
    tm = df['tm'].values
    clo = df['close'].values
    opn = df['open'].values
    vol = df['vol'].values
    hi, lo = df['high'].max(), df['low'].min()
    # 开盘30分钟收益: 10:00 收盘 / 09:31 开盘 - 1
    m1000 = np.searchsorted(tm, 10 * 60)  # 第一个 >= 10:00 的索引
    if m1000 >= len(clo):
        m1000 = len(clo) - 1
    open30_ret = clo[m1000] / opn[0] - 1
    # 尾盘30分钟收益: 15:00 收盘 / 14:30 - 1
    m1430 = np.searchsorted(tm, 14 * 60 + 30)
    if m1430 >= len(clo):
        m1430 = len(clo) - 1
    tail30_ret = clo[-1] / clo[m1430] - 1
    # 尾盘最后5分钟收益: 15:00 收盘 / 14:55 - 1（2026-09-02 新增, 研究窗 t=-14.4 月月为负）
    m1455 = np.searchsorted(tm, 14 * 60 + 55)
    if m1455 >= len(clo):
        m1455 = len(clo) - 1
    tail5_ret = clo[-1] / clo[m1455] - 1
    # 最后一笔量占全日比重（2026-09-02 新增, 尾笔集中度: >p95 组 fwd1 t=-5.8, 涨>2%子集 t=-13.2）
    last_vol_share = float(vol[-1]) / max(float(vol.sum()), 1e-9)
    # VWAP 偏离（停牌/无量股 vol 全 0 → vwap=0，跳过除零）
    vsum = np.sum(vol)
    vwap = np.sum((hi + lo + clo) / 3 * vol) / vsum if vsum > 1e-9 else clo[-1]
    vwap_dev = clo[-1] / vwap - 1
    # 已实现波动率 (分钟收益平方和)
    rt = np.diff(clo) / np.maximum(clo[:-1], 1e-9)
    rv_1m = float(np.sqrt(np.sum(rt ** 2)) * 100)
    # 日内振幅 (vs 开盘)
    amp_intra = (hi - lo) / max(opn[0], 1e-9)
    # 早盘量能占比 (9:31-10:30)
    m1030 = np.searchsorted(tm, 10 * 60 + 30)
    vol_am = vol[:max(m1030, 1)].sum()
    vol_dist_am = vol_am / max(vol.sum(), 1e-9)
    # 尾盘量能占比 (14:30-15:00) —— 2026-08-08 新增: 放量急拉vs缩量急拉判别
    m1430v = np.searchsorted(tm, 14 * 60 + 30)
    vol_tail = vol[m1430v:].sum()
    vol_dist_tail = vol_tail / max(vol.sum(), 1e-9)
    return {
        'date': int(d0), 'n_bars': len(df),
        'open30_ret': round(open30_ret, 6),
        'tail30_ret': round(tail30_ret, 6),
        'tail5_ret': round(tail5_ret, 6),
        'last_vol_share': round(last_vol_share, 6),
        'vwap_dev': round(vwap_dev, 6),
        'rv_1m': round(rv_1m, 6),
        'amp_intra': round(amp_intra, 6),
        'vol_dist_am': round(vol_dist_am, 6),
        'vol_dist_tail': round(vol_dist_tail, 6),
    }

def main(target_date=None):
    files = sorted(glob.glob(str(TDX / 'sh' / 'minline' / '*.lc1')) +
                   glob.glob(str(TDX / 'sz' / 'minline' / '*.lc1')))
    print(f'共 {len(files)} 个 1 分钟文件')
    all_rows = []
    for i, fn in enumerate(files):
        code = Path(fn).stem  # sh600000 → sh600000, 去掉市场前缀
        market = 'sh' if 'sh' in Path(fn).parent.name or fn.split('/')[-1].startswith('sh') else \
                 ('sh' if Path(fn).name.startswith('sh') else 'sz')
        code6 = Path(fn).name[2:8]
        try:
            df = parse_lc1(fn)
            if target_date:
                df = df[df['date'] == int(target_date)]
                if df.empty:
                    continue
            # 按天分组，每天聚合一行（2026-08-08 修：原只取首日日期聚合全历史）
            for date_v, grp in df.groupby('date'):
                r = agg_day(grp)
                if r:
                    r['code'] = code6
                    r['market'] = market
                    all_rows.append(r)
        except Exception as e:
            print(f'  ✗ {Path(fn).name}: {e}')
        if (i + 1) % 1000 == 0:
            print(f'  已解析 {i+1}/{len(files)}')
    if not all_rows:
        print('无数据'); return
    out = pd.DataFrame(all_rows)
    print(f'聚合完成: {len(out)} 行 (每天每只 1 行)')

    s = sqlite3.connect(str(STATE_DB))
    s.execute("""CREATE TABLE IF NOT EXISTS tdx_intraday_feat (
        date INTEGER, code TEXT, market TEXT, n_bars INTEGER,
        open30_ret REAL, tail30_ret REAL, vwap_dev REAL,
        rv_1m REAL, amp_intra REAL, vol_dist_am REAL, vol_dist_tail REAL,
        PRIMARY KEY (date, code))""")
    # 2026-09-02 新增列（tail5急拉+尾笔集中度），已有库自动补列
    _have = {r[1] for r in s.execute("PRAGMA table_info(tdx_intraday_feat)").fetchall()}
    for _col in ('tail5_ret', 'last_vol_share'):
        if _col not in _have:
            s.execute(f"ALTER TABLE tdx_intraday_feat ADD COLUMN {_col} REAL")
    if target_date:
        s.execute("DELETE FROM tdx_intraday_feat WHERE date=?", (int(target_date),))
    else:
        s.execute("DELETE FROM tdx_intraday_feat")
    s.executemany(
        "INSERT OR REPLACE INTO tdx_intraday_feat "
        "(date,code,market,n_bars,open30_ret,tail30_ret,vwap_dev,rv_1m,amp_intra,vol_dist_am,vol_dist_tail,tail5_ret,last_vol_share) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        out[['date', 'code', 'market', 'n_bars', 'open30_ret', 'tail30_ret',
             'vwap_dev', 'rv_1m', 'amp_intra', 'vol_dist_am', 'vol_dist_tail',
             'tail5_ret', 'last_vol_share']].values.tolist())
    s.commit()
    n = s.execute("SELECT COUNT(*) FROM tdx_intraday_feat").fetchone()[0]
    nd = s.execute("SELECT COUNT(DISTINCT date) FROM tdx_intraday_feat").fetchone()[0]
    print(f'✅ 写入 signals.db: tdx_intraday_feat 共 {n} 行, {nd} 个交易日')
    s.close()

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
