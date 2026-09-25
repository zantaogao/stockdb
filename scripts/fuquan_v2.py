# -*- coding: utf-8 -*-
"""真·前复权实现（2026-09-24 建立，两台通用）

背景：scripts/feat_tushare.py::apply_forward_adjust 自 2026-08-01 起是**恒等空壳**
      （算完复权因子仍 `np.array(closes) * 1.0` 返回原始价），导致模型特征的价格类
      与布林带全部按「不复权」计算 → 除权票在除权日被喂进 -28% 的假跳空，
      配合模型对超跌的结构性偏好，被推到全市场满分档（实测 001225 除权日 100.0 百分位，
      真复权口径下只 90.0；300803 为 99.6 vs 52.3）。
本模块提供正确实现，供「影子评分 / 训练对照变体 / 分析脚本」使用，
**不修改生产路径**（生产推理仍是旧口径，改口径需连同模型重训一起切换）。

参考实现：scripts/feat_tushare_tdx.py::apply_forward_adjust（带 dates 版，正确）
"""
import numpy as np


def apply_forward_adjust(closes, highs, lows, adj_factors):
    """前复权：qfq[i] = raw[i] * f[i] / f[-1]

    adj_factors: [(date, factor), ...] 按日期升序，**允许是全历史**（长于 closes）——
                 调用处（core/scoring._compute_ml_features、train_*.py）传的就是全历史
                 adj_factor 配最近 N 根价格，故此处按尾部对齐（adj_factor 逐日有行）。
    返回：np.float64 数组三元组（与旧空壳的返回类型保持一致，避免调用方踩类型差异）
    """
    fac = [float(f) for _, f in adj_factors if f is not None]
    n = len(closes)
    if not fac or n == 0:
        return closes, highs, lows
    tail = fac[-n:] if len(fac) >= n else ([fac[0]] * (n - len(fac)) + fac)
    base = tail[-1]
    if base <= 0:
        return closes, highs, lows
    c = np.array(closes, dtype=np.float64) * (np.array(tail) / base)
    h = np.array(highs, dtype=np.float64) * (np.array(tail) / base)
    l = np.array(lows, dtype=np.float64) * (np.array(tail) / base)
    return c, h, l


def selftest():
    """自测：构造一次 10 送 4（adj_factor 1.0 → 1.4，假跌 -28.6%）的序列，
    断言复权后除权日无跳空。用法：python3 -B scripts/fuquan_v2.py"""
    raw = [50.0, 50.92, 36.37, 37.03]          # 除权前两日 + 除权后两日
    fac = [('20260921', 1.1146), ('20260922', 1.1146), ('20260923', 1.5605), ('20260924', 1.5605)]
    c, _, _ = apply_forward_adjust(raw, raw, raw, fac)
    r_raw = raw[2] / raw[1] - 1
    r_adj = c[2] / c[1] - 1
    print(f'  不复权口径 除权日收益 {r_raw:+.2%}（假跳空）')
    print(f'  前复权口径 除权日收益 {r_adj:+.2%}')
    assert abs(r_adj) < 0.02, '复权后不应再有跳空'
    # 无除权事件时，复权不该改变任何东西（等比缩放）
    fac2 = [('d1', 2.0), ('d2', 2.0), ('d3', 2.0), ('d4', 2.0)]
    c2, _, _ = apply_forward_adjust(raw, raw, raw, fac2)
    assert all(abs(a - b) < 1e-9 for a, b in zip(c2, raw)), '无除权时应恒等'
    print('  ✅ 自测通过（除权日跳空已消除；无除权时恒等）')


if __name__ == '__main__':
    selftest()
