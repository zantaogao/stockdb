#!/usr/bin/env python3
"""
40d 增量 v2 vs 旧模型 — w40 真窗口 IC 对比（阶段 2，2026-08-07 备用）
=============================================================
对 ic_window 中每个已回填 ic_reg40_w40 的信号日：
  1. 用增量 v2 模型（+旧 stats）重算该日全市场 reg40 分
  2. 计算 corr(增量分, T→T+40日收益) = 增量 w40 IC
  3. 对比旧模型（ic_window.ic_reg40_w40）

判定（用户 08-07 决策链的收尾验证）：
  - 增量 v2 w40 IC 显著高于旧模型 → 旧模型退化实锤，建议部署增量
  - 接近或更低 → 旧模型仍有效，维持现状

预计耗时：N 信号日 × ~4 分钟（全市场特征重算）。后台运行。
"""
import sys, json, sqlite3, time
from pathlib import Path
import duckdb
import lightgbm as lgb
import numpy as np
from scipy import stats

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.db import TUSHARE_DB_PATH
from core.scoring import _compute_ml_features

INC_MODEL = BASE / 'models/lgb_reg_40d_inc_v2.txt'
INC_STATS = BASE / 'models/v6_norm_stats_40d_tushare_v2_stkfactor.json'


def main():
    t0 = time.time()
    conn = sqlite3.connect(str(BASE / 'state.db'))
    sig_dates = [r[0] for r in conn.execute(
        "SELECT signal_date FROM ic_window WHERE ic_reg40_w40 IS NOT NULL ORDER BY signal_date"
    ).fetchall()]
    old_ics = {r[0]: r[1] for r in conn.execute(
        "SELECT signal_date, ic_reg40_w40 FROM ic_window WHERE ic_reg40_w40 IS NOT NULL"
    ).fetchall()}
    conn.close()

    if not sig_dates:
        print("w40 尚未回填，退出"); return
    print(f"对比信号日: {len(sig_dates)} 天 ({sig_dates[0]}~{sig_dates[-1]})")

    # 全市场股票
    tconn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
    stocks = [r[0] for r in tconn.execute(
        "SELECT symbol FROM stock_basic WHERE market != '北交所' AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%'"
    ).fetchall()]

    # 交易日历（找每个信号日的 +40 交易日终点）
    tdays = [str(r[0]) for r in tconn.execute(
        "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
    td_idx = {d: i for i, d in enumerate(tdays)}

    # 批量取信号日与终点日价格
    m_inc = lgb.Booster(model_file=str(INC_MODEL))
    s_inc = json.load(open(str(INC_STATS)))

    def normalize(f29):
        Xn = np.array(f29, dtype=np.float64).reshape(1, -1)
        for j in range(Xn.shape[1]):
            key = f'feat_{j}'
            if key in s_inc and s_inc[key]['std'] > 0:
                Xn[:, j] = np.clip(Xn[:, j], s_inc[key]['low'], s_inc[key]['high'])
                Xn[:, j] = (Xn[:, j] - s_inc[key]['mean']) / s_inc[key]['std']
        return np.nan_to_num(Xn, nan=0.0)

    results = []
    for sd in sig_dates:
        sd_clean = sd.replace('-', '')
        if sd_clean not in td_idx or td_idx[sd_clean] + 40 >= len(tdays):
            continue
        end = tdays[td_idx[sd_clean] + 40]
        scores, rets = [], []
        for code in stocks:
            try:
                f29, _ = _compute_ml_features(code, tconn, as_of_date=sd_clean)
                if f29 is None:
                    continue
                pred = m_inc.predict(normalize(f29))[0]
            except Exception:
                continue
            ts = f"{code}.SH" if code.startswith(('6', '9')) else f"{code}.SZ"
            px = tconn.execute(
                "SELECT trade_date, close FROM daily WHERE ts_code=? AND trade_date IN (?, ?) ORDER BY trade_date",
                [ts, sd_clean, end]).fetchall()
            if len(px) != 2 or not px[0][1] or not px[1][1]:
                continue
            ret = (float(px[1][1]) / float(px[0][1]) - 1) * 100
            scores.append(pred)
            rets.append(ret)
        if len(scores) < 100:
            continue
        ic_inc = stats.spearmanr(scores, rets)[0]
        results.append((sd, old_ics.get(sd), round(float(ic_inc), 4), len(scores)))

    tconn.close()

    print(f"\n{'signal_date':<12}{'旧模型w40':>12}{'增量v2 w40':>12}{'样本':>8}")
    inc_ics = []
    for sd, old, inc, n in results:
        print(f"{sd:<12}{old:>12.4f}{inc:>12.4f}{n:>8}")
        inc_ics.append(inc)

    if len(results) >= 3:
        old_mean = np.mean([r[1] for r in results])
        inc_mean = np.mean([r[2] for r in results])
        print(f"\n均值对比: 旧模型 {old_mean:+.4f} vs 增量v2 {inc_mean:+.4f} (n={len(results)})")
        if inc_mean - old_mean > 0.05:
            print("→ 增量 v2 显著优于旧模型：40d 基础退化实锤，建议部署增量（需用户拍板）")
        elif inc_mean >= old_mean:
            print("→ 增量 v2 略优于旧模型：可继续观察")
        else:
            print("→ 增量 v2 不优于旧模型：旧模型仍有效，维持现状")
    print(f"\n耗时: {(time.time()-t0)/60:.1f} min")


if __name__ == '__main__':
    main()
