#!/usr/bin/env python3
"""技术指标自算引擎 (bfq/不复权口径, 对齐 tushare stk_factor extra._bfq)
2026-08-26 由对拍探针 _cron_indicator_probe.py 锁定全部参数:
  MA 简单平均 | MACD EMA12/26/9 hist=2*(dif-dea) | KDJ 9,3,3 SMA递推 J=3K-2D
  RSI Wilder递推(ewm alpha=1/n) | BOLL 20,2 ddof=0 | CCI 14
  ROC 12 | MTM 12 | WR 10 | DMI 14,6 全SMA(非Wilder) | OBV cumsum(sign*vol/10000)上市首日起点
  turnover_rate/volume_ratio 直接用 daily_basic(与 stk_factor extra 100%一致)
输入: tushare.db daily(全历史) + daily_basic
输出: 每股票每交易日 -> dict(键名同 tushare extra: ma_bfq_5, macd_dif_bfq, ...)
"""
import duckdb, json, time, sys
import numpy as np
import pandas as pd

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
MIN_HIST = 60  # 不足60天历史不计算(与模型要求一致)

# ── 指标实现(输入 df: 单股全历史升序, 含 open/high/low/close/pre_close/vol) ──

def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def compute_indicators(df: pd.DataFrame) -> dict:
    """df: 单股全历史升序 DataFrame, 列含 trade_date/open/high/low/close/pre_close/vol.
    返回 {date8: {key: value}}, 键名对齐 tushare extra。"""
    if len(df) < MIN_HIST:
        return {}
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['vol']
    dates = df['trade_date'].astype(str).str.replace('-', '').values

    out = {}

    # MA
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    # MACD
    dif = _ema(close, 12) - _ema(close, 26)
    dea = _ema(dif, 9)
    macd_ = 2 * (dif - dea)

    # KDJ 9,3,3 (SMA 递推 = ewm alpha=1/3)
    llv = low.rolling(9).min()
    hhv = high.rolling(9).max()
    rsv = (close - llv) / (hhv - llv) * 100
    rsv = rsv.fillna(50.0)
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3*k - 2*d

    # RSI (Wilder 递推 = ewm alpha=1/n)
    def _rsi(n):
        diff = close.diff()
        gain = diff.clip(lower=0)
        loss = -diff.clip(upper=0)
        ag = gain.ewm(alpha=1/n, adjust=False).mean()
        al = loss.ewm(alpha=1/n, adjust=False).mean()
        rs = ag / al
        return 100 - 100 / (1 + rs)
    rsi6, rsi12, rsi24 = _rsi(6), _rsi(12), _rsi(24)

    # BOLL 20,2 ddof=0
    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    bup = mid + 2*std
    blo = mid - 2*std

    # CCI 14
    tp = (high + low + close) / 3
    tp_ma = tp.rolling(14).mean()
    tp_md = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci_ = (tp - tp_ma) / (0.015 * tp_md)

    # ROC 12 / MTM 12
    roc_ = (close - close.shift(12)) / close.shift(12) * 100
    mtm_ = close - close.shift(12)

    # WR 10
    hhv10 = high.rolling(10).max()
    llv10 = low.rolling(10).min()
    wr_ = (hhv10 - close) / (hhv10 - llv10) * 100

    # DMI 14,6 全 SMA (tushare 口径, 非 Wilder)
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_s = tr.rolling(14).mean()
    pdm_s = pd.Series(plus_dm, index=df.index).rolling(14).mean()
    mdm_s = pd.Series(minus_dm, index=df.index).rolling(14).mean()
    pdi = 100 * pdm_s / atr_s
    mdi = 100 * mdm_s / atr_s
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    adx = dx.rolling(6).mean()

    # OBV: cumsum(sign * vol/10000), 上市首日起点
    # sign 用"真实昨收"=close.shift(1) 而非 daily.pre_close:
    #   除权除息日 daily.pre_close 是调整后参考价(如7/13 3.42), 而 tushare 用真实昨收(3.59)
    #   判断涨跌 → 除息日不复权价看似下跌但 tushare 按真实涨跌计 (2026-08-26 对拍锁定)
    sign = np.sign(close - close.shift(1)).fillna(0)
    obv_ = (sign * vol / 10000).cumsum()

    series_map = {
        'ma_bfq_5': ma5, 'ma_bfq_20': ma20, 'ma_bfq_60': ma60,
        'macd_dif_bfq': dif, 'macd_dea_bfq': dea, 'macd_bfq': macd_,
        'kdj_k_bfq': k, 'kdj_d_bfq': d, 'kdj_bfq': j,
        'rsi_bfq_6': rsi6, 'rsi_bfq_12': rsi12, 'rsi_bfq_24': rsi24,
        'boll_upper_bfq': bup, 'boll_mid_bfq': mid, 'boll_lower_bfq': blo,
        'cci_bfq': cci_, 'roc_bfq': roc_, 'mtm_bfq': mtm_, 'wr_bfq': wr_,
        'dmi_pdi_bfq': pdi, 'dmi_mdi_bfq': mdi, 'dmi_adx_bfq': adx,
        'obv_bfq': obv_,
    }

    for key, s in series_map.items():
        vals = s.values
        for i in range(len(dates)):
            v = vals[i]
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                out.setdefault(dates[i], {})[key] = round(float(v), 4)
    return out


def compute_all(codes, progress=1000):
    """批量计算多只股票。返回 {ts_code: {date8: {key: value}}}"""
    c = duckdb.connect(DB, read_only=True)
    result = {}
    for i, code in enumerate(codes):
        df = c.execute(f"""
            SELECT trade_date, open, high, low, close, pre_close, vol
            FROM daily WHERE ts_code='{code}' ORDER BY trade_date ASC
        """).fetchdf()
        if len(df) == 0:
            continue
        result[code] = compute_indicators(df)
        if (i + 1) % progress == 0:
            print(f"  已计算 {i+1}/{len(codes)}", flush=True)
    c.close()
    return result


def write_to_db(result, db_path):
    """把自算指标写入独立库 indicators.db (表 indicator_bfq: ts_code, trade_date, 指标列...)
    覆盖式写入(整表重建): 幂等, 每次全量重算后覆盖, 避免增量维护。
    独立库设计: 不碰 tushare.db(只读铁律) 和 ledger.db/signals.db(交易状态)。
    """
    import duckdb as _dk
    rows = []
    for code, dd in result.items():
        for date8, kv in dd.items():
            kv2 = dict(kv)
            kv2['ts_code'] = code
            kv2['trade_date'] = date8
            rows.append(kv2)
    if not rows:
        print("⚠️ 无数据可写")
        return
    import pandas as _pd
    df = _pd.DataFrame(rows)
    con = _dk.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS indicator_bfq (ts_code VARCHAR, trade_date VARCHAR)")
    # 重建: 删旧表按新列建(列集稳定, 重建保证无残留列)
    con.execute("DROP TABLE IF EXISTS indicator_bfq")
    con.execute("CREATE TABLE indicator_bfq AS SELECT * FROM df")
    n = con.execute("SELECT COUNT(*) FROM indicator_bfq").fetchone()[0]
    dmin, dmax = con.execute("SELECT MIN(trade_date), MAX(trade_date) FROM indicator_bfq").fetchone()
    con.close()
    print(f"✅ 写入 {db_path}: {n} 行, 覆盖 {dmin}~{dmax}")


if __name__ == '__main__':
    t0 = time.time()
    c = duckdb.connect(DB, read_only=True)
    codes = [r[0] for r in c.execute("SELECT DISTINCT ts_code FROM daily WHERE trade_date >= '20260101'").fetchall()]
    c.close()
    print(f"计算 {len(codes)} 只股票的技术指标...")
    res = compute_all(codes)
    print(f"完成: {len(res)} 只, 耗时 {time.time()-t0:.0f}s")
    # 输出到 parquet 便于对拍
    rows = []
    for code, dd in res.items():
        for date8, kv in dd.items():
            kv2 = dict(kv); kv2['ts_code'] = code; kv2['trade_date'] = date8
            rows.append(kv2)
    out_df = pd.DataFrame(rows)
    out_path = '/tmp/indicators_bfq.parquet'
    out_df.to_parquet(out_path)
    print(f"写入 {out_path}: {len(out_df)} 行, 覆盖 {out_df['trade_date'].min()}~{out_df['trade_date'].max()}")
