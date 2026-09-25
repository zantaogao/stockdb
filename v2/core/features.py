"""
v2 特征工程 — 单一入口，面向A股量化回归模型
================================================
设计原则：
1. 每个因子有明确的经济学含义
2. 输出固定维度，带名称列表
3. 包含标准化/去极值逻辑
4. 训练和推理用同一套代码

数据源（stock.db）：
- stock_daily: OHLCV + change_pct (已复权)
- stk_limit: 涨跌停价 → 判断是否触板
- money_flow_full: 主力资金净流入
- stock_valuation: PE/PB/市值
- stk_fin_income: ROE等财务指标
- index_daily: 行业基准指数

目标变量：20日超额收益率（相对所属行业基准）
"""
import numpy as np
from pathlib import Path


# ─── 特征名称与分类 ────────────────────────────────────────
# 按因子类别分组，便于后续IC分析时追溯含义

FEAT_GROUPS = {
    'momentum':   ['chg5', 'chg10', 'chg20', 'chg60'],       # 动量: N日收益率
    'deviation':  ['d5_ma', 'd20_ma', 'd60_ma'],              # 偏离度: 相对MA的偏离
    'volatility': ['std10', 'std20', 'atr20'],                # 波动率
    'volume':     ['vol_ratio5', 'vol_trend', 'amount_rank'],  # 量能
    'position':   ['pos20', 'pos60', 'near_up_limit', 'near_down_limit'],  # 价格位置
    'trend':      ['ma_alignment', 'higher_high'],            # 趋势形态
    'valuation':  ['ep_ttm', 'pb', 'ln_circ_mv'],             # 估值/市值
    'fundflow':   ['mf_net_5d', 'mf_net_20d', 'mf_ratio'],    # 资金流
    'reversal':   ['dn_streak', 'up_ratio10', 'vol_accel'],   # 反转信号
}

FEAT_NAMES = []
for group_feats in FEAT_GROUPS.values():
    FEAT_NAMES.extend(group_feats)

N_FEATURES = len(FEAT_NAMES)  # 25


def compute_features(code, daily_rows, limit_rows, mf_rows, val_dict, fin_dict):
    """
    计算全部特征。

    Args:
        code: 股票代码 (str)
        daily_rows: stock_daily查询结果，ORDER BY date DESC，每行:
            (date, open, close, high, low, volume, amount, amplitude, change_pct, turn_rate)
        limit_rows: stk_limit查询结果 ORDER BY date DESC:
            (date, up_limit, down_limit) — 日期格式 'YYYYMMDD'
        mf_rows: money_flow_full查询结果 ORDER BY trade_date DESC:
            (trade_date, buy_sm_amount, sell_sm_amount, ..., net_mf_amount, ...)
        val_dict: {ep_ttm, pb, ln_circ_mv} — 最新估值数据，缺失用None
        fin_dict: {roe} — 最新ROE，缺失用None

    Returns:
        feat_vec: np.array (N_FEATURES,) 或 None（数据不足）
        latest_date: str 'YYYY-MM-DD'
    """
    if len(daily_rows) < 120:
        return None, None

    # 统一转为时间升序
    rows = daily_rows[::-1]
    n = len(rows)

    closes  = np.array([float(r[2]) for r in rows], dtype=np.float64)   # close
    opens   = np.array([float(r[1]) for r in rows], dtype=np.float64)   # open
    highs   = np.array([float(r[3]) for r in rows], dtype=np.float64)   # high
    lows    = np.array([float(r[4]) for r in rows], dtype=np.float64)   # low
    volumes = np.array([float(r[5] or 0) for r in rows], dtype=np.float64)

    lc = closes[-1]

    # ── change_pct: DB里可能为None，自己算 ──
    returns = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        if closes[i-1] > 0:
            returns[i] = (closes[i] / closes[i-1]) - 1

    # ─── Momentum (4) ──────────────────────────────────────
    chg5   = lc / closes[-6]  - 1 if n >= 6  else 0.0
    chg10  = lc / closes[-11] - 1 if n >= 11 else 0.0
    chg20  = lc / closes[-21] - 1 if n >= 21 else 0.0
    chg60  = lc / closes[-61] - 1 if n >= 61 else 0.0

    # ─── Deviation (3) — 相对MA的偏离度 ─────────────────────
    ma5  = np.mean(closes[-5:])  if n >= 5  else lc
    ma20 = np.mean(closes[-20:]) if n >= 20 else lc
    ma60 = np.mean(closes[-60:]) if n >= 60 else lc

    d5_ma   = (lc / ma5)  - 1 if ma5  > 0 else 0.0
    d20_ma  = (lc / ma20) - 1 if ma20 > 0 else 0.0
    d60_ma  = (lc / ma60) - 1 if ma60 > 0 else 0.0

    # ─── Volatility (3) ─────────────────────────────────────
    std10 = float(np.std(returns[-10:])) * np.sqrt(252) if n >= 10 else 0.0
    std20 = float(np.std(returns[-20:])) * np.sqrt(252) if n >= 20 else 0.0

    # ATR (Average True Range) 20日
    if n >= 21:
        true_ranges = np.zeros(n, dtype=np.float64)
        for i in range(1, n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i]   - closes[i-1]))
            true_ranges[i] = tr
        atr20 = float(np.mean(true_ranges[-20:])) / lc  # 归一化为百分比
    else:
        atr20 = 0.0

    # ─── Volume (3) ─────────────────────────────────────────
    # 5日量比: 今日成交量 / 5日均量
    vol_ratio5 = volumes[-1] / np.mean(volumes[-6:-1]) if n >= 6 and np.mean(volumes[-6:-1]) > 0 else 1.0

    # 量能趋势: 近5均量 vs 近20均量的比值
    if n >= 20:
        vol_trend = np.mean(volumes[-5:]) / (np.mean(volumes[-20:-15]) + 1e-15) - 1
    else:
        vol_trend = 0.0

    # 成交额横截面排名（需要全市场数据，这里用近60日相对分位替代）
    if n >= 60:
        amounts = np.array([float(r[6] or 0) for r in rows], dtype=np.float64)
        recent_amt = amounts[-1]
        hist_amts = amounts[-60:-1]
        if len(hist_amts) > 0 and np.max(hist_amts) > np.min(hist_amts):
            amount_rank = (recent_amt - np.min(hist_amts)) / (np.max(hist_amts) - np.min(hist_amts) + 1e-15)
        else:
            amount_rank = 0.5
    else:
        amount_rank = 0.5

    # ─── Position (4) — 价格位置与涨跌停 ─────────────────────
    # 20日/60日内价格分位
    if n >= 20:
        lo20, hi20 = np.min(closes[-20:]), np.max(closes[-20:])
        pos20 = (lc - lo20) / (hi20 - lo20 + 1e-15) if hi20 > lo20 else 0.5
    else:
        pos20 = 0.5

    if n >= 60:
        lo60, hi60 = np.min(closes[-60:]), np.max(closes[-60:])
        pos60 = (lc - lo60) / (hi60 - lo60 + 1e-15) if hi60 > lo60 else 0.5
    else:
        pos60 = 0.5

    # 涨跌停距离（A股特色因子）
    near_up_limit = 0.0
    near_down_limit = 0.0
    if limit_rows and len(limit_rows) > 0:
        # limit_rows是DESC，取最新一条
        latest_limit = limit_rows[0]
        up_price = float(latest_limit[1]) if latest_limit[1] else 0
        down_price = float(latest_limit[2]) if latest_limit[2] else 0
        if up_price > 0:
            near_up_limit = (lc - up_price) / lc  # 负值表示离涨停还有多远
        if down_price > 0:
            near_down_limit = (lc - down_price) / lc  # 正值表示离跌停还有多远

    # ─── Trend (2) — 趋势形态 ────────────────────────────────
    # MA多头排列: MA5 > MA10 > MA20 > MA60
    ma10 = np.mean(closes[-10:]) if n >= 10 else lc
    ma_alignment = int(ma5 > ma10 and ma10 > ma20 and ma20 > ma60)

    # 近期创新高: 今日是否接近20日新高
    higher_high = int(lc > hi20 * 0.98) if n >= 20 else 0

    # ─── Valuation (3) — 估值/市值 ────────────────────────────
    ep_ttm = val_dict.get('ep_ttm', 0.0) if val_dict else 0.0
    pb_val = val_dict.get('pb', 1.0) if val_dict else 1.0
    ln_circ_mv = val_dict.get('ln_circ_mv', 22.0) if val_dict else 22.0

    # ─── Fund flow (3) — 资金流（A股特色）─────────────────────
    mf_net_5d = 0.0
    mf_net_20d = 0.0
    mf_ratio = 0.0

    if mf_rows and len(mf_rows) > 0:
        # mf_rows是DESC，net_mf_amount在索引8
        mf_nets = [float(r[8] or 0) for r in mf_rows[:20]]  # 最近20个交易日
        if len(mf_nets) >= 5:
            mf_net_5d = sum(mf_nets[:5])   # 单位：万元
        if len(mf_nets) >= 20:
            mf_net_20d = sum(mf_nets[:20])

        # 资金流相对成交额的比例
        if n >= 5 and val_dict and val_dict.get('ln_circ_mv') is not None:
            circ_mv = np.exp(ln_circ_mv)  # 还原市值（元）
            avg_daily_amt = np.mean([float(rows[-i][6] or 0) for i in range(1, 6)])  # 5日均成交额
            if avg_daily_amt > 0:
                mf_ratio = sum(mf_nets[:5]) * 1e4 / (avg_daily_amt + 1e-15)  # 净流入/日均成交额

    # ─── Reversal (3) — 反转信号 ──────────────────────────────
    # 连续下跌天数（从最新往前数）
    dn_streak = 0
    for i in range(len(returns)-1, max(-1, len(returns)-21), -1):
        if returns[i] < 0:
            dn_streak += 1
        else:
            break

    # 近10日上涨天数占比
    up_ratio10 = float(np.sum(returns[-10:] > 0)) / 10.0 if n >= 10 else 0.5

    # 波动率加速度: 近5日std vs 前5-10日std
    if n >= 15:
        std_recent = float(np.std(returns[-5:]))
        std_earlier = float(np.std(returns[-10:-5]))
        vol_accel = (std_recent - std_earlier) / (std_earlier + 1e-15)
    else:
        vol_accel = 0.0

    # ─── Assemble ─────────────────────────────────────────────
    feat_vec = np.array([
        chg5, chg10, chg20, chg60,           # momentum (4)
        d5_ma, d20_ma, d60_ma,                # deviation (3)
        std10, std20, atr20,                  # volatility (3)
        vol_ratio5, vol_trend, amount_rank,   # volume (3)
        pos20, pos60, near_up_limit, near_down_limit,  # position (4)
        ma_alignment, higher_high,            # trend (2)
        ep_ttm, pb_val, ln_circ_mv,           # valuation (3)
        mf_net_5d, mf_net_20d, mf_ratio,      # fundflow (3)
        dn_streak, up_ratio10, vol_accel,     # reversal (3)
    ], dtype=np.float64)

    latest_date = str(rows[-1][0])[:10] if rows else None

    return feat_vec, latest_date


def winorize(features, method='mad', k=5.0):
    """
    Winsorize: 用MAD方法去极值，比±3σ更鲁棒。

    Args:
        features: np.array (N, D)
        method: 'mad' or 'percentile'
        k: MAD倍数或百分位阈值

    Returns:
        winsorized array
    """
    result = features.copy()

    if method == 'mad':
        median = np.nanmedian(features, axis=0)
        mad = np.nanmedian(np.abs(features - median), axis=0) * 1.4826
        for j in range(result.shape[1]):
            if mad[j] > 0:
                lo = median[j] - k * mad[j]
                hi = median[j] + k * mad[j]
                result[:, j] = np.clip(result[:, j], lo, hi)

    elif method == 'percentile':
        for j in range(result.shape[1]):
            lo = np.nanpercentile(features[:, j], k)
            hi = np.nanpercentile(features[:, j], 100 - k)
            result[:, j] = np.clip(result[:, j], lo, hi)

    return result


def standardize(features, mean=None, std=None):
    """
    Z-score标准化。传入mean/std则用训练集统计量，否则计算当前数据的。

    Returns:
        standardized array, (mean, std) tuple
    """
    if mean is None:
        mean = np.nanmean(features, axis=0)
    if std is None:
        std = np.nanstd(features, axis=0)

    result = (features - mean) / (std + 1e-15)
    return result, mean, std


def rank_normalize(features):
    """
    横截面rank标准化（机构常用做法）。
    将每列转换为[0,1]区间的百分位排名。

    Args:
        features: np.array (N, D) — 一天全市场的特征矩阵

    Returns:
        rank-normalized array (N, D)
    """
    result = np.zeros_like(features)
    for j in range(features.shape[1]):
        col = features[:, j]
        # argsort of argsort gives ranks
        ranks = np.argsort(np.argsort(col)).astype(np.float64)
        n = len(ranks)
        result[:, j] = ranks / (n - 1)  # [0, 1]

    return result


def save_norm_stats(mean, std, path):
    """保存标准化统计量供推理使用"""
    import json
    stats = {}
    for j, name in enumerate(FEAT_NAMES):
        if j < len(mean):
            stats[name] = {
                'mean': float(mean[j]),
                'std':  float(std[j]),
            }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(stats, f, indent=2)


def load_norm_stats(path):
    """加载标准化统计量"""
    import json
    with open(path) as f:
        stats = json.load(f)
    mean = np.array([stats[name]['mean'] for name in FEAT_NAMES])
    std  = np.array([stats[name]['std']  for name in FEAT_NAMES])
    return mean, std
