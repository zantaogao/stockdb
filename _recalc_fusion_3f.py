"""历史重算 fusion_3f_signals 8/3-8/10（2026-08-10 reg10 方向修正后）
每日期：as_of 动态参数（当日窗口）→ 新符号 calc_fusion_3f → 当日百分位分级 → DELETE+INSERT
用法: python3 -B _recalc_fusion_3f.py [起始日] [截止日]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sqlite3
import numpy as np
from fusion_3f_engine import calc_fusion_3f, compute_dynamic_params, STATE_DB

start = sys.argv[1] if len(sys.argv) > 1 else '20260803'
end = sys.argv[2] if len(sys.argv) > 2 else '20260810'

conn = sqlite3.connect(STATE_DB, timeout=30)
dates = [str(r[0]) for r in conn.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM new_factors WHERE REPLACE(date,'-','') BETWEEN ? AND ? ORDER BY 1",
    (start, end)).fetchall()]
print(f'重算日期: {dates}')

for sd in dates:
    params = compute_dynamic_params(conn, as_of=sd)
    ma_mean, ma_std, flow_mean, flow_std, vol_mean, vol_std = params

    rows = conn.execute("""
        SELECT
            nf.stock_code, nf.date, nf.ma_decay,
            fa.flow_alpha, va.vol_adj,
            COALESCE(sh.reg10, 0) as reg10
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
        WHERE REPLACE(nf.date, '-', '') = ?
          AND (sb.name NOT LIKE '%ST%' AND sb.name NOT LIKE '%退%')
          AND (sb.market IS NULL OR sb.market != '北交所')
    """, (sd,)).fetchall()

    reg10_all = np.array([(r[5] if r[5] else 0) for r in rows], dtype=float)
    if len(reg10_all) > 100:
        center = float(np.median(reg10_all))
        mad = float(np.median(np.abs(reg10_all - center)))
        scale = max(1.4826 * mad, 0.001)
    else:
        center, scale = 0.03, 0.05

    results = []
    for r in rows:
        fusion = calc_fusion_3f({
            'ma_decay': r[2], 'flow_alpha': r[3], 'vol_adj': r[4], 'reg10': r[5] or 0,
        }, params=params, reg10_center=center, reg10_scale=scale)
        results.append({'stock_code': r[0], 'date': r[1], 'reg10': r[5] or 0,
                        'ma_decay': r[2], 'flow_alpha': r[3], 'vol_adj': r[4],
                        'fusion_3f': round(fusion, 2)})

    scores = sorted(x['fusion_3f'] for x in results)
    n = len(scores)
    buy_t = scores[int(n * 0.85)]
    hold_top = scores[int(n * 0.60)]
    hold_bot = scores[int(n * 0.40)]
    sell_t = scores[int(n * 0.15)]
    def assign(s):
        if s >= buy_t: return '强买'
        if s >= hold_top: return '买'
        if s >= hold_bot: return '持'
        if s >= sell_t: return '卖'
        return '强卖'

    # DELETE 当天（兼容横杠/无横杠）+ INSERT
    conn.execute(f"DELETE FROM fusion_3f_signals WHERE REPLACE(date,'-','') = '{sd}'")
    for x in results:
        conn.execute("""
            INSERT OR REPLACE INTO fusion_3f_signals
            (stock_code, date, reg10, ma_decay, flow_alpha, vol_adj, fusion_3f_score, signal)
            VALUES (?,?,?,?,?,?,?,?)
        """, (x['stock_code'], x['date'], x['reg10'], x['ma_decay'], x['flow_alpha'],
              x['vol_adj'], x['fusion_3f'], assign(x['fusion_3f'])))
    conn.commit()
    strong = sum(1 for x in results if assign(x['fusion_3f']) == '强买')
    print(f'  {sd}: {len(results)} 只 (强买 {strong}, 中心 {center:+.4f}, 缩放 {scale:.4f})')

conn.close()
print('✅ 重算完成')
