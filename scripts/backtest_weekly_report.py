#!/usr/bin/env python3
"""策略回测周报：合并三因子强买 / CMMR / CMMR+ 三个回测，按信号日对齐对比"""
import sqlite3, numpy as np, sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
STATE_DB = _SCRIPT_DIR / 'signals.db'  # v2温层

def main():
    conn = sqlite3.connect(str(STATE_DB))
    
    # 三因子强买回测
    fb = {r[0]: r for r in conn.execute("""
        SELECT signal_date, sb_ew, sb_win, n_sb, mkt_ew, ss_ew, top10_ew, ls_ret
        FROM fusion_3f_backtest ORDER BY signal_date
    """).fetchall()}
    # CMMR 回测
    cb = {r[0]: r for r in conn.execute("""
        SELECT signal_date, cmmr_ew, cmmr_n, cmmr_win, cmmr80_ew, fsc_ew, fsc_n, fsc_win, mkt_ew
        FROM cmmr_backtest ORDER BY signal_date
    """).fetchall()}

    all_dates = sorted(set(fb) | set(cb))
    if not all_dates:
        print("无回测数据（fusion_3f_backtest / cmmr_backtest 均为空）")
        return

    print("=" * 96)
    print("策略等权回测周报（T+1 收益，单位 %）")
    print("=" * 96)
    print(f"{'信号日':<10}{'三因子强买':<10}{'CMMR独立':<10}{'CMMR+融合':<10}{'全市场':<10}{'强买超额':<10}{'CMMR超额':<10}{'CMMR+超额':<10}")
    print("-" * 96)

    rows = []
    for d in all_dates:
        f = fb.get(d)
        c = cb.get(d)
        sb = f[1] if f else None
        cm = c[1] if c else None
        fsc = c[5] if c else None
        mkt = (f[4] if f and f[4] is not None else c[8]) if (f or c) else None
        # 市场用强买回测的（同一天两者应一致，取非 None）
        if f and f[4] is not None:
            mkt = f[4]
        elif c and c[8] is not None:
            mkt = c[8]
        rows.append((d, sb, cm, fsc, mkt))
        
        def fmt(v):
            return f"{v:+.2f}%" if v is not None else "  -  "
        print(f"{d:<10}{fmt(sb):<10}{fmt(cm):<10}{fmt(fsc):<10}{fmt(mkt):<10}"
              f"{fmt(sb - mkt if sb is not None and mkt is not None else None):<10}"
              f"{fmt(cm - mkt if cm is not None and mkt is not None else None):<10}"
              f"{fmt(fsc - mkt if fsc is not None and mkt is not None else None):<10}")

    # 汇总
    print("-" * 96)
    def mean(col):
        vals = [r[col] for r in rows if r[col] is not None]
        return np.mean(vals) if vals else None
    sb_m, cm_m, fsc_m, mkt_m = mean(1), mean(2), mean(3), mean(4)
    def fmt(v):
        return f"{v:+.2f}%" if v is not None else "  -  "
    print(f"{'累计均值':<10}{fmt(sb_m):<10}{fmt(cm_m):<10}{fmt(fsc_m):<10}{fmt(mkt_m):<10}"
          f"{fmt(sb_m - mkt_m if sb_m is not None and mkt_m is not None else None):<10}"
          f"{fmt(cm_m - mkt_m if cm_m is not None and mkt_m is not None else None):<10}"
          f"{fmt(fsc_m - mkt_m if fsc_m is not None and mkt_m is not None else None):<10}")

    # 按天胜率
    def day_win(col):
        vals = [r for r in rows if r[col] is not None]
        return sum(1 for r in vals if r[col] > 0) / len(vals) * 100 if vals else 0
    print(f"\n按天胜率: 强买 {day_win(1):.0f}% | CMMR {day_win(2):.0f}% | CMMR+ {day_win(3):.0f}% | 市场 {day_win(4):.0f}%")
    print(f"样本天数: {len(rows)}")

    # 三因子强买 Top10% 精选超额（验证分数排序）
    top_excess = [f[6] - f[1] for f in fb.values() if f[1] is not None and f[6] is not None]
    if top_excess:
        print(f"\n分数排序验证: Top10%精选 - 等权 = {np.mean(top_excess):+.2f}%（>0 表示按分数挑更好）")

    # ===== 模型 IC 对比（ic_daily：10d/20d/40d/fusion 单日截面 IC）=====
    ic_rows = conn.execute("""
        SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40
        FROM ic_daily ORDER BY signal_date
    """).fetchall()
    if ic_rows:
        print(f"\n{'='*96}")
        print("模型 IC 对比（Pearson 单日截面，T+1）")
        print(f"{'='*96}")
        print(f"{'信号日':<12}{'融合':<9}{'10d':<9}{'20d':<9}{'40d':<9}")
        print("-" * 48)
        for r in ic_rows:
            def f(v): return f"{v:+.4f}" if v is not None else "  -  "
            print(f"{r[0]:<12}{f(r[1]):<9}{f(r[2]):<9}{f(r[3]):<9}{f(r[4]):<9}")
        # 累计均值 + 胜率
        def ic_stats(idx):
            vals = [r[idx] for r in ic_rows if r[idx] is not None]
            if not vals:
                return None, None
            return np.mean(vals), sum(1 for v in vals if v > 0) / len(vals)
        print("-" * 48)
        for label, idx in [('融合', 1), ('10d', 2), ('20d', 3), ('40d', 4)]:
            m, w = ic_stats(idx)
            if m is not None:
                print(f"{label} 累计: {m:+.4f}  胜率 {w*100:.0f}%  (样本 {sum(1 for r in ic_rows if r[idx] is not None)} 天)")

    conn.close()

if __name__ == '__main__':
    main()
