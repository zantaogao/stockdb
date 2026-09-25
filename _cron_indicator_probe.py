#!/usr/bin/env python3
"""技术指标自算对拍探针: 自算 vs tushare stk_factor extra._bfq 逐指标找最优参数口径
只读 tushare.db。输出: 每指标在参数网格下的相关系数/相对误差, 锁定 tushare 口径。
"""
import duckdb, json, itertools
import numpy as np
import pandas as pd

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
CODES = ['000001.SZ', '600000.SH', '300750.SZ', '688981.SH', '002615.SZ']
HIST_DAYS = 600   # 递推指标计算历史(含起点收敛)
N_DAYS = 120      # 对拍窗口(只对拍最近这些天)

c = duckdb.connect(DB, read_only=True)

def get_ts(code):
    """取该股近HIST_DAYS日线(时间升序), 返回DataFrame"""
    df = c.execute(f"""
        SELECT trade_date, open, high, low, close, pre_close, vol, amount
        FROM daily WHERE ts_code='{code}'
        ORDER BY trade_date DESC LIMIT {HIST_DAYS}
    """).fetchdf()
    return df.iloc[::-1].reset_index(drop=True)

def get_extra(code, date):
    r = c.execute(f"SELECT extra FROM stk_factor WHERE ts_code='{code}' AND trade_date='{date}'").fetchone()
    if not r or not r[0]:
        return {}
    try:
        d = json.loads(r[0])
        return {k: v for k, v in d.items() if isinstance(v, (int, float))}
    except:
        return {}

# ── 指标实现 (输入: df 含 open/high/low/close/pre_close/vol) ──
def ma(s, n): return s.rolling(n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def macd(df):
    dif = ema(df['close'], 12) - ema(df['close'], 26)
    dea = ema(dif, 9)
    macd_ = 2 * (dif - dea)
    return dif, dea, macd_

def kdj(df, n=9, m1=3, m2=3, fillna=True):
    llv = df['low'].rolling(n).min()
    hhv = df['high'].rolling(n).max()
    rsv = (df['close'] - llv) / (hhv - llv) * 100
    if fillna:
        rsv = rsv.fillna(50.0)
    # SMA(X,N,1): y = (x + (N-1)*y_prev)/N
    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3*k - 2*d
    return k, d, j

def rsi(df, n):
    diff = df['close'].diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)
    # Wilder: avg = (prev*(n-1)+cur)/n 等价 ewm(alpha=1/n, adjust=False)
    ag = gain.ewm(alpha=1/n, adjust=False).mean()
    al = loss.ewm(alpha=1/n, adjust=False).mean()
    rs = ag / al
    out = 100 - 100 / (1 + rs)
    return out

def boll(df, n=20, k=2.0, ddof=0):
    mid = df['close'].rolling(n).mean()
    std = df['close'].rolling(n).std(ddof=ddof)
    return mid + k*std, mid, mid - k*std

def cci(df, n=14):
    tp = (df['high'] + df['low'] + df['close']) / 3
    m = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - m) / (0.015 * md)

def roc(df, n):
    return (df['close'] - df['close'].shift(n)) / df['close'].shift(n) * 100

def mtm(df, n):
    return df['close'] - df['close'].shift(n)

def wr(df, n):
    hhv = df['high'].rolling(n).max()
    llv = df['low'].rolling(n).min()
    return (hhv - df['close']) / (hhv - llv) * 100

def dmi(df, n=14, m=6, smooth='ewm', adx_smooth='ewm'):
    """DMI 变体: smooth='ewm'=Wilder递推 / 'sma'=简单平均"""
    up = df['high'].diff()
    down = -df['low'].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift()).abs()
    tr3 = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    if smooth == 'ewm':
        atr = tr.ewm(alpha=1/n, adjust=False).mean()
        pdm_s = pd.Series(plus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean()
        mdm_s = pd.Series(minus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean()
    else:
        atr = tr.rolling(n).mean()
        pdm_s = pd.Series(plus_dm, index=df.index).rolling(n).mean()
        mdm_s = pd.Series(minus_dm, index=df.index).rolling(n).mean()
    pdi = 100 * pdm_s / atr
    mdi = 100 * mdm_s / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    if adx_smooth == 'ewm':
        adx = dx.ewm(alpha=1/m, adjust=False).mean()
    else:
        adx = dx.rolling(m).mean()
    return pdi, mdi, adx

def obv(df):
    sign = np.sign(df['close'] - df['pre_close'])
    return (sign * df['vol']).cumsum()

# ── 对拍 ──
def cmp_series(computed, target_series, name, param_desc):
    """computed: pd.Series(全历史), target_series: {date: value}"""
    pairs = []
    for d, tv in target_series.items():
        if d in computed.index:
            cv = computed.loc[d]
            if pd.notna(cv) and tv is not None and not (isinstance(tv, float) and np.isnan(tv)):
                pairs.append((float(cv), float(tv)))
    if len(pairs) < 30:
        return None
    arr_c = np.array([p[0] for p in pairs]); arr_t = np.array([p[1] for p in pairs])
    if np.std(arr_t) == 0:
        corr = 1.0 if np.allclose(arr_c, arr_t, rtol=1e-6, atol=1e-6) else 0.0
    else:
        corr = float(np.corrcoef(arr_c, arr_t)[0, 1])
    mae = float(np.mean(np.abs(arr_c - arr_t)))
    # 相对误差(按target量级)
    scale = np.mean(np.abs(arr_t)) + 1e-9
    rel = float(np.mean(np.abs(arr_c - arr_t) / scale))
    return corr, mae, rel, len(pairs)

def probe(code, key, calc_fn, param_grids, index_name):
    """calc_fn(params...) -> pd.Series, index_name 用于匹配日期; 只对拍最近 N_DAYS 天"""
    df = get_ts(code)
    df['date8'] = df['trade_date'].astype(str).str.replace('-', '')
    last_dates = set(df['date8'].iloc[-N_DAYS:].values)
    target = {}
    for d in df['date8']:
        if d not in last_dates:
            continue
        ex = get_extra(code, d)
        if key in ex:
            target[d] = ex[key]
    if not target:
        return None
    results = []
    for params in param_grids:
        try:
            s = calc_fn(df, *params)
            s.index = df['date8'].values
            r = cmp_series(s, target, key, params)
            if r:
                results.append((params, r))
        except Exception as e:
            print(f"  ⚠️ {key}{params} 异常: {e}")
    return results

# 参数网格
grids = {
    'ma_bfq_5': [(5,)], 'ma_bfq_20': [(20,)], 'ma_bfq_60': [(60,)],
    'macd_dif_bfq': [()], 'macd_dea_bfq': [()], 'macd_bfq': [()],
    'kdj_k_bfq': [(9,3,3,True), (9,3,3,False), (9,3,2,True)],
    'kdj_d_bfq': [(9,3,3,True), (9,3,3,False), (9,3,2,True)],
    'kdj_j_bfq': [(9,3,3,True), (9,3,3,False), (9,3,2,True)],
    'rsi_bfq_6': [(6,)], 'rsi_bfq_12': [(12,)], 'rsi_bfq_24': [(24,)],
    'kdj_bfq': [(9,3,3,True), (9,3,3,False)],
    'boll_mid_bfq': [(20,2,0), (20,2,1)],
    'boll_upper_bfq': [(20,2,0), (20,2,1)],
    'boll_lower_bfq': [(20,2,0), (20,2,1)],
    'cci_bfq': [(14,), (20,)],
    'roc_bfq': [(6,), (10,), (12,), (20,)],
    'mtm_bfq': [(6,), (10,), (12,), (20,)],
    'wr_bfq': [(6,), (10,), (14,)],
    'dmi_pdi_bfq': [(14,6,'ewm','ewm'), (14,6,'sma','sma'), (14,3,'ewm','ewm'), (14,14,'ewm','ewm'), (14,6,'sma','ewm')],
    'dmi_mdi_bfq': [(14,6,'ewm','ewm'), (14,6,'sma','sma'), (14,3,'ewm','ewm'), (14,14,'ewm','ewm'), (14,6,'sma','ewm')],
    'dmi_adx_bfq': [(14,6,'ewm','ewm'), (14,6,'sma','sma'), (14,3,'ewm','ewm'), (14,14,'ewm','ewm'), (14,6,'sma','ewm')],
    'obv_bfq': [()],
}

fns = {
    'ma_bfq_5': lambda df, n: ma(df['close'], n),
    'ma_bfq_20': lambda df, n: ma(df['close'], n),
    'ma_bfq_60': lambda df, n: ma(df['close'], n),
    'macd_dif_bfq': lambda df: macd(df)[0],
    'macd_dea_bfq': lambda df: macd(df)[1],
    'macd_bfq': lambda df: macd(df)[2],
    'kdj_k_bfq': lambda df, n, m1, m2, f: kdj(df, n, m1, m2, f)[0],
    'kdj_d_bfq': lambda df, n, m1, m2, f: kdj(df, n, m1, m2, f)[1],
    'kdj_j_bfq': lambda df, n, m1, m2, f: kdj(df, n, m1, m2, f)[2],
    'rsi_bfq_6': lambda df, n: rsi(df, n),
    'rsi_bfq_12': lambda df, n: rsi(df, n),
    'rsi_bfq_24': lambda df, n: rsi(df, n),
    'kdj_bfq': lambda df, n, m1, m2, f: kdj(df, n, m1, m2, f)[2],
    'boll_mid_bfq': lambda df, n, k, dd: boll(df, n, k, dd)[1],
    'boll_upper_bfq': lambda df, n, k, dd: boll(df, n, k, dd)[0],
    'boll_lower_bfq': lambda df, n, k, dd: boll(df, n, k, dd)[2],
    'cci_bfq': lambda df, n: cci(df, n),
    'roc_bfq': lambda df, n: roc(df, n),
    'mtm_bfq': lambda df, n: mtm(df, n),
    'wr_bfq': lambda df, n: wr(df, n),
    'dmi_pdi_bfq': lambda df, n, m, s, a: dmi(df, n, m, s, a)[0],
    'dmi_mdi_bfq': lambda df, n, m, s, a: dmi(df, n, m, s, a)[1],
    'dmi_adx_bfq': lambda df, n, m, s, a: dmi(df, n, m, s, a)[2],
    'obv_bfq': lambda df: obv(df),
}

print(f"{'指标':<12} {'参数':<16} {'corr':<8} {'MAE':<10} {'relErr':<8} {'n'}")
print("-" * 70)
for key, param_list in grids.items():
    all_res = []
    for code in CODES:
        r = probe(code, key, fns[key], param_list, 'date8')
        if r:
            all_res.append(r)
    # 汇总: 每个参数组合求所有股票corr均值
    for i, params in enumerate(param_list):
        corrs = []
        for r_list in all_res:
            if i < len(r_list):
                corrs.append(r_list[i][1][0])
        if corrs:
            mc = np.mean(corrs)
            best = max(all_res, key=lambda rl: rl[i][1][0] if i < len(rl) else -1)[i]
            corr, mae, rel, n = best[1]
            flag = ' ✅' if corr > 0.999 else ''
            print(f"{key:<12} {str(params):<16} {mc:<8.5f} {mae:<10.4g} {rel:<8.4g} {n}{flag}")

# 单独输出 turnover_rate / volume_ratio 对照 daily_basic
print("\n── turnover_rate / volume_ratio: stk_factor extra vs daily_basic ──")
for code in CODES:
    df = get_ts(code)
    df['date8'] = df['trade_date'].astype(str).str.replace('-', '')
    db = c.execute(f"""
        SELECT trade_date, turnover_rate, volume_ratio FROM daily_basic
        WHERE ts_code='{code}' ORDER BY trade_date DESC LIMIT {N_DAYS}
    """).fetchdf()
    db['date8'] = db['trade_date'].astype(str).str.replace('-', '')
    db = db.set_index('date8')
    n_match = 0; n_tot = 0; diff_sum = 0.0
    for d in df['date8']:
        ex = get_extra(code, d)
        if 'turnover_rate' in ex and d in db.index and pd.notna(db.loc[d, 'turnover_rate']):
            n_tot += 1
            if abs(ex['turnover_rate'] - float(db.loc[d, 'turnover_rate'])) < 1e-6:
                n_match += 1
            else:
                diff_sum += abs(ex['turnover_rate'] - float(db.loc[d, 'turnover_rate']))
    if n_tot:
        print(f"{code}: turnover 一致率 {n_match}/{n_tot}, 不一致均值差 {diff_sum/max(n_tot-n_match,1):.4g}")

c.close()
print("\n✅ probe 完成")
