#!/usr/bin/env python3
"""center_dual (中枢版+三模型) 组合信号 IC 每日计算 (2026-08-27 新增)
口径与策略账户 center_dual 完全一致: 0.5*pct(fusion_center score) + 0.5*pct(fusion_score)
逐信号日算次日 Spearman IC + Top10 收益。落库 signals.db.center_dual_ic_daily, 幂等(主键覆盖)。
"""
import sqlite3, sys
import numpy as np
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import duckdb
from scipy.stats import spearmanr

STATE_DB = BASE / 'signals.db'  # v2温层
TUSHARE_DB = BASE / 'tushare.db'
SIG_START = '20260807'  # fusion_center 信号起点(08-06 上线, 08-07 首日信号)


def main():
    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    tdu = duckdb.connect(str(TUSHARE_DB), read_only=True)

    # 兼容旧表：补 fwd10/20/40_top10 列（2026-08-28 新增：Top10 等权 10/20/40 交易日窗口收益）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(center_dual_ic_daily)").fetchall()]
    for _c in ('fwd10_top10', 'fwd20_top10', 'fwd40_top10'):
        if _c not in cols:
            conn.execute(f"ALTER TABLE center_dual_ic_daily ADD COLUMN {_c} REAL")
            print(f"  表加列 {_c}")

    # 交易日序列
    tdays = [str(r[0]) for r in tdu.execute(
        "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
    td_idx = {d: i for i, d in enumerate(tdays)}

    # 信号日(center 信号有数据的)
    sig_dates = [str(r[0]).replace('-', '') for r in conn.execute(
        "SELECT DISTINCT REPLACE(date,'-','') FROM fusion_center_signals "
        "WHERE REPLACE(date,'-','') >= ? ORDER BY 1", (SIG_START,)).fetchall()]
    print(f"center_dual IC: 信号日 {len(sig_dates)} 个 ({sig_dates[0] if sig_dates else '无'}~{sig_dates[-1] if sig_dates else ''})")

    # 建表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS center_dual_ic_daily (
            date TEXT PRIMARY KEY,
            ic REAL,
            samples INTEGER,
            top_ret REAL,
            bottom_ret REAL,
            ic_diff REAL,
            fwd10_top10 REAL,
            fwd20_top10 REAL,
            fwd40_top10 REAL,
            calc_date TEXT
        )
    """)

    n_saved = 0
    for sd in sig_dates:
        if sd not in td_idx or td_idx[sd] + 1 >= len(tdays):
            continue  # 无次日收益(最新信号日), 跳过
        nd = tdays[td_idx[sd] + 1]

        ct_rows = conn.execute(
            "SELECT stock_code, score FROM fusion_center_signals "
            "WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (sd,)).fetchall()
        md_rows = conn.execute(
            "SELECT stock_code, fusion_score FROM signal_history "
            "WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (sd,)).fetchall()
        ctmap = {r[0]: float(r[1]) for r in ct_rows}
        mdmap = {r[0]: float(r[1]) for r in md_rows}
        common = sorted(set(ctmap) & set(mdmap))
        if len(common) < 1000:
            continue

        n = len(common)
        ct_rank = np.argsort(np.argsort([ctmap[x] for x in common])) + 1
        md_rank = np.argsort(np.argsort([mdmap[x] for x in common])) + 1
        comb = {x: 0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                for i, x in enumerate(common)}

        # 次日收益
        closes = {}
        for d_ in (sd, nd):
            for ts, c in tdu.execute("SELECT ts_code, close FROM daily WHERE trade_date=?",
                                     [d_]).fetchall():
                closes.setdefault(ts, {})[d_] = float(c)

        rets, scores, codes = [], [], []
        for sc, s in comb.items():
            full = f"{sc}.SH" if sc.startswith(('6', '9')) else f"{sc}.SZ"
            p = closes.get(full)
            if not p or sd not in p or nd not in p:
                continue
            rets.append(p[nd] / p[sd] - 1)
            scores.append(s)
            codes.append(sc)
        if len(rets) < 500:
            continue

        rho = float(spearmanr(scores, rets).statistic)
        ordered = sorted(zip(codes, scores, rets), key=lambda x: x[1], reverse=True)
        k = max(1, int(len(ordered) * 0.10))
        top_ret = float(np.mean([r for _, _, r in ordered[:k]])) * 100
        bottom_ret = float(np.mean([r for _, _, r in ordered[-k:]])) * 100

        # Top10 只（执行口径）10/20/40 交易日窗口等权收益（2026-08-28 新增，百分数落库；窗口未满=None）
        top10_codes = [c for c, _, _ in ordered[:10]]
        fwd_vals = {}
        for n_days, col in ((10, 'fwd10_top10'), (20, 'fwd20_top10'), (40, 'fwd40_top10')):
            fi = td_idx[sd] + n_days
            if fi >= len(tdays):
                fwd_vals[col] = None
                continue
            fd = tdays[fi]
            ph = {ts: float(c) for ts, c in tdu.execute(
                "SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN (%s)"
                % ','.join('?' * len(top10_codes)), [fd] + [f"{c}.SH" if c.startswith(('6', '9')) else f"{c}.SZ" for c in top10_codes]).fetchall()}
            rs = []
            for c in top10_codes:
                full = f"{c}.SH" if c.startswith(('6', '9')) else f"{c}.SZ"
                p0 = closes.get(full, {}).get(sd)
                p1 = ph.get(full)
                if p0 and p1:
                    rs.append(p1 / p0 - 1)
            fwd_vals[col] = round(float(np.mean(rs)) * 100, 3) if rs else None

        conn.execute("""
            INSERT OR REPLACE INTO center_dual_ic_daily
            (date, ic, samples, top_ret, bottom_ret, ic_diff, fwd10_top10, fwd20_top10, fwd40_top10, calc_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sd, rho, len(rets), top_ret, bottom_ret, top_ret - bottom_ret,
              fwd_vals['fwd10_top10'], fwd_vals['fwd20_top10'], fwd_vals['fwd40_top10'],
              __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')))
        n_saved += 1
        fwd_s = ' '.join(f"fwd{n}={fwd_vals[f'fwd{n}_top10']:+.2f}%" if fwd_vals[f'fwd{n}_top10'] is not None else f"fwd{n}=-"
                         for n in (10, 20, 40))
        print(f"  {sd}: IC={rho:+.4f} 样本={len(rets)} Top10%={top_ret:+.2f}% Bot10%={bottom_ret:+.2f}% {fwd_s}")

    conn.commit()
    # 汇总
    rows = conn.execute("SELECT date, ic FROM center_dual_ic_daily ORDER BY date").fetchall()
    if rows:
        ics = [r[1] for r in rows if r[1] is not None]
        if len(ics) >= 3:
            print(f"\n汇总: {len(rows)} 天, 均值 IC={np.mean(ics):+.4f} 标准差={np.std(ics):+.4f} "
                  f"胜率={np.mean([1 if x > 0 else 0 for x in ics]) * 100:.0f}%")
    conn.close(); tdu.close()
    print(f"✅ center_dual_ic_daily 更新 {n_saved} 天")


if __name__ == '__main__':
    main()
