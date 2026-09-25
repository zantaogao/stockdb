#!/usr/bin/env python3
"""IC 质量评估：按口径分层统计（诊断用，不写库）"""
import sqlite3, numpy as np

BASE = '/Users/zantao/.hermes/stockdb'
s = sqlite3.connect(f'{BASE}/state.db')

def stats(vals, label):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        print(f'  {label}: 样本 {len(vals)}（不足）')
        return
    a = np.array(vals)
    mean = a.mean()
    std = a.std(ddof=1) if len(a) > 1 else 0
    ir = mean / std if std > 0 else 0
    t = ir * np.sqrt(len(a))
    win = (a > 0).mean() * 100
    print(f'  {label}: n={len(a)} 均值={mean:+.4f} std={std:.4f} IR={ir:+.2f} t={t:+.2f} 胜率={win:.0f}%')

print('═══ 1. 窗口期 IC（ic_window，真预测窗口）═══')
rows = s.execute("SELECT signal_date, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40, ic_fusion_w10, ic_fusion_w20, ic_fusion_w40, ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, fwd10_top, fwd20_top, fwd40_top FROM ic_window ORDER BY signal_date").fetchall()
print(f'  总行数: {len(rows)}（10日窗口最早 8/6 到期，20日 8/20，40日 ~9月底）')
if rows:
    for r in rows[-8:]:
        print(f'  {r[0]}: reg10_w10={r[1]} reg20_w20={r[2]} reg40_w40={r[3]} fus_w10={r[4]} fus_w20={r[5]} fus_w40={r[6]} 3f_w10={r[7]} cmmr_w10={r[8]} cmmrf_w10={r[9]} fwd10={r[10]} fwd20={r[11]} fwd40={r[12]}')

print()
print('═══ 2. 次日 IC 哨兵（ic_daily，T→T+1，窗口错配仅作健康哨兵）═══')
rows = s.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, ic_final FROM ic_daily ORDER BY signal_date").fetchall()
print(f'  信号日数: {len(rows)}，跨度 {rows[0][0]} → {rows[-1][0]}')
for label, idx in [('融合', 1), ('10d', 2), ('20d', 3), ('40d', 4), ('final', 5)]:
    stats([r[idx] for r in rows], label)

print()
print('═══ 3. 策略 IC（cmmr_ic_daily / fusion_ic_daily，次日）═══')
rows = s.execute("SELECT date, ic FROM cmmr_ic_daily ORDER BY date").fetchall()
print(f'  CMMR 信号日数: {len(rows)}')
stats([r[1] for r in rows], 'CMMR')
rows = s.execute("SELECT date, ic FROM fusion_ic_daily ORDER BY date").fetchall()
print(f'  CMMR+ 信号日数: {len(rows)}')
stats([r[1] for r in rows], 'CMMR+')

print()
print('═══ 4. 等权组合验证（backtest 表，T+1 等权收益）═══')
for tname, cols, label in [
    ('fusion_3f_backtest', ('sb_ew', 'mkt_ew', 'top10_ew'), '三因子强买'),
    ('cmmr_backtest', ('cmmr_ew', 'cmmr80_ew', 'fsc_ew'), 'CMMR/CMMR+'),
]:
    try:
        rows = s.execute(f"SELECT signal_date, {','.join(cols)} FROM {tname} ORDER BY signal_date").fetchall()
        print(f'  {label}（{tname}）: {len(rows)} 个信号日')
        for r in rows:
            print(f'    {r[0]}: ' + ' | '.join(f'{c}={r[i+1]:+.2f}%' for i, c in enumerate(cols)))
        if len(rows) >= 2:
            for i, c in enumerate(cols):
                stats([r[i+1] for r in rows], c)
    except Exception as e:
        print(f'  {label}: ERR {e}')

print()
print('═══ 5. 参考：单日 IC 截面显著性（最近日，n≈4900）═══')
r = s.execute("SELECT signal_date, ic_fusion FROM ic_daily ORDER BY signal_date DESC LIMIT 1").fetchone()
if r and r[1] is not None:
    n = 4914
    t_sec = r[1] * np.sqrt(n - 2) / np.sqrt(1 - r[1]**2)
    print(f'  {r[0]} 融合次日 IC={r[1]:+.4f}：截面 t={t_sec:+.1f}（单日排序信息显著），但这是哨兵口径')
