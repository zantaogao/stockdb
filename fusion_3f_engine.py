#!/usr/bin/env python3
"""
三因子融合10d引擎
新建 fusion_3f_signals 表，不碰现有 signal_history 和因子表。

融合规则：
1. reg10 < 0.03 → 方向看多
2. 三因子标准化加权 → fusion_3f_score
3. 信号分级：强买/买/持/卖/强卖

数据源：
- new_factors (ma_decay)
- flow_alpha (flow_alpha)  
- vol_adj (vol_adj)
- signal_history (reg10, fusion_score)

写入：fusion_3f_signals 表（stock_code, date, reg10, fusion_3f_score, signal）
"""

import sqlite3
import sys
import numpy as np
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 保证 core.db 可 import(与 cwd 无关)
from core.db import connect_signals

STATE_DB = '/Users/zantao/.hermes/stockdb/signals.db'  # v2温层(留档, 连接走统一入口)

# 因子标准化参数（基于滚动窗口，动态计算）
# 默认值（历史统计，首次运行前使用）
MA_DECAY_MEAN = 1.347
MA_DECAY_STD = 28.5
FLOW_ALPHA_MEAN = -0.023
FLOW_ALPHA_STD = 0.012
VOL_ADJ_MEAN = 0.110
VOL_ADJ_STD = 0.075
ROLLING_WINDOW = 20  # 滚动窗口天数

def get_latest_date(conn):
    """获取最新日期（从 new_factors 取，因子驱动融合）"""
    r = conn.execute(
        "SELECT date FROM new_factors ORDER BY REPLACE(date, '-', '') DESC LIMIT 1"
    ).fetchone()
    if r and r[0]:
        return r[0]
    return '2026-07-24'

def calc_fusion_3f(row, params=None, reg10_center=0.03, reg10_scale=0.05):
    """
    计算三因子融合分（0-100）。
    支持动态参数（params 元组）或全局默认参数。
    reg10_center/reg10_scale：方向中心与缩放，默认 0.03/0.05（历史先验），
    实际运行时由 run() 用当日 reg10 分布动态计算（模型每周重训后自动跟随）。
    返回 fusion_3f_score（信号分级在 run() 中按当日百分位做）
    """
    ma_decay = row.get('ma_decay', 0) or 0
    flow_alpha = row.get('flow_alpha', 0) or 0
    vol_adj = row.get('vol_adj', 0) or 0
    reg10 = row.get('reg10', 0) or 0
    
    # 使用动态参数或全局默认
    if params:
        ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std = params
    else:
        ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std = (
            MA_DECAY_MEAN, MA_DECAY_STD, FLOW_ALPHA_MEAN, FLOW_ALPHA_STD,
            VOL_ADJ_MEAN, VOL_ADJ_STD
        )
    
    # 标准化（Z-score）
    ma_z = (ma_decay - ma_mean) / ma_std
    flow_z = (flow_alpha - flow_mean) / flow_std
    vol_z = -(vol_adj - vol_mean) / vol_std  # 负号：vol_adj越低越好
    
    # 加权融合 (0.3*ma + 0.3*flow + 0.2*vol + 0.2*reg10_direction)
    # reg10方向：⚠️ 2026-08-10 修正——reg10 v3 是正向模型（训练 y=未来10日收益，验证集
    # IC=+0.1604，十分组 D1:-1.97%→D10:+4.50% 单调递增），高分=预测高收益=看涨。
    # 原 `-(reg10-center)` 把正向模型当负向用（08-10 实测 fusion_3f IC 被拖累至 -0.12，
    # 修正后 +0.22）。旧"reg10<0.03 看涨"认知源于 7/31 重训前旧模型，已过时。
    reg_z = (reg10 - reg10_center) / reg10_scale
    
    raw_score = 0.3 * ma_z + 0.3 * flow_z + 0.2 * vol_z + 0.2 * reg_z
    
    # 映射到 0-100（假设raw_score在[-2, 2]之间，映射到[0, 100]）
    fusion_3f = max(0, min(100, (raw_score + 2) / 4 * 100))
    
    return fusion_3f

def compute_dynamic_params(conn, window=ROLLING_WINDOW, as_of=None):
    """
    从最近 N 个交易日计算动态标准化参数。
    as_of: 截止日期 YYYYMMDD（2026-08-10 新增——历史重算 fusion_3f 时用当日窗口，
           避免用未来数据算参数；默认 None=最新）
    返回 (ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std)
    """
    # 取最近 window 个交易日（按日期去重排序，避免跨月减法 bug）
    if as_of:
        recent_dates = conn.execute("""
            SELECT DISTINCT REPLACE(date, '-', '') as d FROM new_factors
            WHERE REPLACE(date, '-', '') <= ?
            ORDER BY d DESC LIMIT ?
        """, (as_of, window)).fetchall()
    else:
        recent_dates = conn.execute("""
            SELECT DISTINCT REPLACE(date, '-', '') as d FROM new_factors
            ORDER BY d DESC LIMIT ?
        """, (window,)).fetchall()
    if not recent_dates:
        print(f"  用默认参数: MA={MA_DECAY_MEAN:.3f}/{MA_DECAY_STD:.1f}  Flow={FLOW_ALPHA_MEAN:.3f}/{FLOW_ALPHA_STD:.3f}  Vol={VOL_ADJ_MEAN:.3f}/{VOL_ADJ_STD:.3f}")
        return MA_DECAY_MEAN, MA_DECAY_STD, FLOW_ALPHA_MEAN, FLOW_ALPHA_STD, VOL_ADJ_MEAN, VOL_ADJ_STD

    # 取这些日期的最小值作为窗口起点（转回 YYYY-MM-DD 与表中日期格式一致）
    start_date = recent_dates[-1][0]
    start_date_iso = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    print(f"  动态窗口: {start_date_iso} ~ {recent_dates[0][0][:4]}-{recent_dates[0][0][4:6]}-{recent_dates[0][0][6:]}（{len(recent_dates)} 个交易日）")

    rows = conn.execute("""
        SELECT
            nf.ma_decay,
            fa.flow_alpha,
            va.vol_adj
        FROM new_factors nf
        JOIN flow_alpha fa
            ON nf.stock_code = fa.stock_code AND nf.date = fa.date
        JOIN vol_adj va
            ON nf.stock_code = va.stock_code AND nf.date = va.date
        WHERE nf.date >= ?
          AND nf.ma_decay IS NOT NULL
          AND fa.flow_alpha IS NOT NULL
          AND va.vol_adj IS NOT NULL
    """, (start_date_iso,)).fetchall()

    if not rows:
        print(f"  用默认参数: MA={MA_DECAY_MEAN:.3f}/{MA_DECAY_STD:.1f}  Flow={FLOW_ALPHA_MEAN:.3f}/{FLOW_ALPHA_STD:.3f}  Vol={VOL_ADJ_MEAN:.3f}/{VOL_ADJ_STD:.3f}")
        return MA_DECAY_MEAN, MA_DECAY_STD, FLOW_ALPHA_MEAN, FLOW_ALPHA_STD, VOL_ADJ_MEAN, VOL_ADJ_STD

    ma_vals = np.array([r[0] for r in rows if r[0] is not None])
    flow_vals = np.array([r[1] for r in rows if r[1] is not None])
    vol_vals = np.array([r[2] for r in rows if r[2] is not None])

    def robust_stats(vals):
        """截断 1%~99% 后的均值和标准差（抵御 ma_decay 分母爆炸等离群值）"""
        if len(vals) < 100:
            return float(np.mean(vals)), float(np.std(vals))
        lo, hi = np.percentile(vals, 1), np.percentile(vals, 99)
        v = vals[(vals >= lo) & (vals <= hi)]
        return float(np.mean(v)), float(np.std(v))

    ma_mean, ma_std = robust_stats(ma_vals)
    flow_mean, flow_std = robust_stats(flow_vals)
    vol_mean, vol_std = robust_stats(vol_vals)

    # 防止 std 为 0（取最小值 0.001）
    ma_std = max(ma_std, 0.001)
    flow_std = max(flow_std, 0.001)
    vol_std = max(vol_std, 0.001)

    print(f"  动态参数: MA={ma_mean:.4f}/{ma_std:.4f}  Flow={flow_mean:.4f}/{flow_std:.4f}  Vol={vol_mean:.4f}/{vol_std:.4f}")
    return ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std


def run():
    print("=" * 50)
    print("三因子融合10d引擎")
    print("=" * 50)

    conn = connect_signals()  # 统一入口(v2温层)

    # 计算动态标准化参数（基于最近 N 天）
    print("计算动态标准化参数（最近20天）...")
    ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std = compute_dynamic_params(conn)
    print()

    # 创建表（如果不存在）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fusion_3f_signals (
            stock_code TEXT NOT NULL,
            date TEXT NOT NULL,
            reg10 REAL,
            ma_decay REAL,
            flow_alpha REAL,
            vol_adj REAL,
            fusion_3f_score REAL,
            signal TEXT,
            PRIMARY KEY (stock_code, date)
        )
    """)
    
    latest_date = get_latest_date(conn)
    latest_date_clean = latest_date.replace('-', '')
    print(f"处理日期: {latest_date} (clean: {latest_date_clean})")
    
    # 先删当天的旧数据（兼容有横杠和无横杠）
    conn.execute(
        f"DELETE FROM fusion_3f_signals WHERE REPLACE(date, '-', '') = '{latest_date_clean}'"
    )
    
    # 获取数据：JOIN new_factors + flow_alpha + vol_adj + signal_history
    rows = conn.execute(f"""
        SELECT 
            nf.stock_code,
            nf.date,
            nf.ma_decay,
            fa.flow_alpha,
            va.vol_adj,
            COALESCE(sh.reg10, 0) as reg10,
            COALESCE(sh.fusion_score, 50) as fusion_score
        FROM new_factors nf
        LEFT JOIN flow_alpha fa 
            ON REPLACE(nf.stock_code, '.', '') = REPLACE(fa.stock_code, '.', '')
            AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
        LEFT JOIN vol_adj va 
            ON REPLACE(nf.stock_code, '.', '') = REPLACE(va.stock_code, '.', '')
            AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
        LEFT JOIN signal_history sh 
            ON REPLACE(nf.stock_code, '.', '') = REPLACE(sh.stock_code, '.', '')
            AND REPLACE(nf.date, '-', '') = REPLACE(sh.date, '-', '')
        LEFT JOIN stock_basic sb ON sb.stock_code = nf.stock_code
        WHERE REPLACE(nf.date, '-', '') = '{latest_date_clean}'
          AND (sb.name NOT LIKE '%ST%' AND sb.name NOT LIKE '%退%')
          AND (sb.market IS NULL OR sb.market != '北交所')
    """).fetchall()
    
    print(f"读取 {len(rows)} 条数据")
    
    # 计算当日 reg10 动态中心/缩放（模型每周重训，固定 0.03 会失效）
    # 用当日全市场 reg10 分布：中心=中位数（方向分界），缩放=1.4826*MAD（稳健）
    reg10_all = np.array([(r[5] if r[5] else 0) for r in rows], dtype=float)
    if len(reg10_all) > 100:
        reg10_center = float(np.median(reg10_all))
        mad = float(np.median(np.abs(reg10_all - reg10_center)))
        reg10_scale = max(1.4826 * mad, 0.001)
        print(f"  reg10 动态方向: 中心={reg10_center:+.4f} 缩放={reg10_scale:.4f} "
              f"(<中心占比 {(reg10_all < reg10_center).mean()*100:.0f}%)")
    else:
        reg10_center, reg10_scale = 0.03, 0.05
        print(f"  样本不足，用默认 reg10 中心 0.03")
    
    # 第一步：计算所有融合分（不含信号）
    raw_results = []
    for row in rows:
        stock_code = row[0]
        date = row[1]
        reg10 = row[5] if row[5] else 0
        
        fusion_3f = calc_fusion_3f({
            'ma_decay': row[2],
            'flow_alpha': row[3],
            'vol_adj': row[4],
            'reg10': reg10,
        }, params=(ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std),
           reg10_center=reg10_center, reg10_scale=reg10_scale)
        
        raw_results.append({
            'stock_code': stock_code,
            'date': date,
            'reg10': reg10,
            'ma_decay': row[2],
            'flow_alpha': row[3],
            'vol_adj': row[4],
            'fusion_3f': round(fusion_3f, 2),
        })
    
    # 第二步：按当日融合分百分位做信号分级
    scores = sorted([r['fusion_3f'] for r in raw_results])
    n = len(scores)
    # 百分位阈值：强买(top 15%) > 买(15-40%) > 持(40-60%) > 卖(60-85%) > 强卖(bottom 15%)
    buy_threshold = scores[int(n * 0.85)]     # 前15%是强买
    hold_top = scores[int(n * 0.60)]           # 前40%是买（含强买）
    hold_bot = scores[int(n * 0.40)]           # 后40%是卖（含强卖）
    sell_threshold = scores[int(n * 0.15)]     # 后15%是强卖
    
    def assign_signal(score):
        if score >= buy_threshold:
            return '强买'
        elif score >= hold_top:
            return '买'
        elif score >= hold_bot:
            return '持'
        elif score >= sell_threshold:
            return '卖'
        else:
            return '强卖'
    
    # 应用信号
    results = []
    for r in raw_results:
        results.append((
            r['stock_code'], r['date'], r['reg10'],
            r['ma_decay'], r['flow_alpha'], r['vol_adj'],
            r['fusion_3f'], assign_signal(r['fusion_3f'])
        ))
    
    print(f"信号阈值: 强买≥{buy_threshold:.0f}  买≥{hold_top:.0f}  持≥{hold_bot:.0f}  卖≥{sell_threshold:.0f}  强卖<{sell_threshold:.0f}")
    
    # 批量插入
    conn.executemany("""
        INSERT INTO fusion_3f_signals 
        (stock_code, date, reg10, ma_decay, flow_alpha, vol_adj, fusion_3f_score, signal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, results)
    
    conn.commit()
    
    # 统计（只统计今天）
    stats = conn.execute(f"""
        SELECT signal, COUNT(*) 
        FROM fusion_3f_signals 
        WHERE REPLACE(date, '-', '') = '{latest_date_clean}'
        GROUP BY signal 
        ORDER BY COUNT(*) DESC
    """).fetchall()
    
    print("\n=== 信号分布 ===")
    for sig, cnt in stats:
        print(f"  {sig}: {cnt} ({cnt/len(rows)*100:.1f}%)")
    
    # 验证：强买 vs 强卖的均值（只统计今天）
    strong_buy = conn.execute(f"""
        SELECT AVG(reg10), AVG(fusion_3f_score) FROM fusion_3f_signals 
        WHERE signal = '强买' AND REPLACE(date, '-', '') = '{latest_date_clean}'
    """).fetchone()
    strong_sell = conn.execute(f"""
        SELECT AVG(reg10), AVG(fusion_3f_score) FROM fusion_3f_signals 
        WHERE signal = '强卖' AND REPLACE(date, '-', '') = '{latest_date_clean}'
    """).fetchone()
    
    print(f"\n强买: reg10={strong_buy[0]:.4f}, fusion_3f={strong_buy[1]:.2f}")
    print(f"强卖: reg10={strong_sell[0]:.4f}, fusion_3f={strong_sell[1]:.2f}")

    # 对比新旧参数下的强买组分数分布
    print(f"\n=== 标准化参数对比 ===")
    print(f"  动态: MA={ma_mean:.4f}/{ma_std:.4f}  Flow={flow_mean:.4f}/{flow_std:.4f}  Vol={vol_mean:.4f}/{vol_std:.4f}")
    print(f"  固定: MA={MA_DECAY_MEAN:.3f}/{MA_DECAY_STD:.1f}  Flow={FLOW_ALPHA_MEAN:.3f}/{FLOW_ALPHA_STD:.3f}  Vol={VOL_ADJ_MEAN:.3f}/{VOL_ADJ_STD:.3f}")
    
    # 示例数据（只显示今天）
    print(f"\n=== 示例数据（前5条）===")
    examples = conn.execute(f"""
        SELECT stock_code, reg10, fusion_3f_score, signal 
        FROM fusion_3f_signals 
        WHERE REPLACE(date, '-', '') = '{latest_date_clean}'
        ORDER BY fusion_3f_score DESC 
        LIMIT 5
    """).fetchall()
    for e in examples:
        print(f"  {e[0]}: reg10={e[1]:.4f}, fusion_3f={e[2]:.2f}, {e[3]}")
    
    conn.close()
    print(f"\n完成！写入 {len(results)} 条记录 → fusion_3f_signals")
    return results


if __name__ == '__main__':
    run()
