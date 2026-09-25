#!/usr/bin/env python3
"""CMMR 双策略等权回测（cron 版）
1. CMMR 独立: cmmr_score > 0 等权（纯防守选股）
2. CMMR+ 融合: fusion_score_cmmr 按当日百分位 top 15% 等权（与三因子强买 15% 对齐）
3. 对照: 全市场等权 + CMMR 高分(>=80) 子集
结果写入 state.db 的 cmmr_backtest 表（signal_date 幂等）
"""
import sqlite3, duckdb, numpy as np, sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

STATE_DB = _SCRIPT_DIR / 'signals.db'  # v2温层
TUSHARE_DB = _SCRIPT_DIR / 'tushare.db'

def ts_code(code):
    code = str(code)
    return f'{code}.SH' if code.startswith(('6','68','9')) else f'{code}.SZ'

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cmmr_backtest (
            signal_date TEXT PRIMARY KEY,
            cmmr_ew REAL, cmmr_n INTEGER, cmmr_win REAL,
            cmmr80_ew REAL, cmmr80_n INTEGER,
            fsc_ew REAL, fsc_n INTEGER, fsc_win REAL,
            mkt_ew REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 2026-09-11 加列：与 cmmr 策略账户实际选池同口径（≥80 地板 + 档内按
    # fusion_score 次级排序取 top10 等权）。原 cmmr_ew（>0 全池等权）保留作
    # 历史连续序列，但账户 09-06 起地板已提至 ≥80，报告口径以本列为准。
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cmmr_backtest)")]
    if 'cmmr80_top10_ew' not in cols:
        conn.execute("ALTER TABLE cmmr_backtest ADD COLUMN cmmr80_top10_ew REAL")
        print("  cmmr_backtest 已添加 cmmr80_top10_ew 列")

def compute_day(state, tushare, d):
    nd = tushare.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", (d,)).fetchone()[0]
    if not nd:
        return None

    rows = state.execute("""
        SELECT stock_code, cmmr_score, fusion_score_cmmr, COALESCE(fusion_score, 0) FROM signal_history
        WHERE REPLACE(date,'-','')=?
    """, (d,)).fetchall()
    if not rows:
        return None

    ts_list = [ts_code(r[0]) for r in rows]
    ph = ','.join(['?']*len(ts_list))
    p0 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (d,)+tuple(ts_list)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (nd,)+tuple(ts_list)).fetchall()}

    items = []
    for code, cmmr, fsc, fs in rows:
        ts = ts_code(code)
        if ts in p0 and ts in p1 and p0[ts] > 0:
            items.append({'code': code, 'cmmr': float(cmmr or 0),
                          'fsc': float(fsc or 0), 'fs': float(fs or 0),
                          'ret': (p1[ts]/p0[ts]-1)*100})
    if not items:
        return None

    # CMMR 独立: cmmr_score > 0
    cmmr = [i for i in items if i['cmmr'] > 0]
    # CMMR 高分: >= 80
    cmmr80 = [i for i in items if i['cmmr'] >= 80]
    # CMMR80 top10: 与策略账户实际选池同口径（2026-09-11）——
    # ≥80 地板 + 先按档位降序、档内按 fs(三模型融合原始分 fusion_score) 降序取前 10
    # （与 strategy_accounts_daily.get_signal_targets cmmr 分支 ORDER BY 完全同键序）。
    top10 = sorted([i for i in items if i['cmmr'] >= 80],
                   key=lambda i: (-i['cmmr'], -i['fs'], i['code']))[:10]
    # CMMR+ 融合: fusion_score_cmmr 当日 top 15%（百分位 p85）
    fsc_vals = sorted(i['fsc'] for i in items)
    n = len(fsc_vals)
    p85 = fsc_vals[int(n * 0.85)] if n > 0 else 0
    fsc = [i for i in items if i['fsc'] >= p85]

    # 全市场等权
    mkt0 = {r[0]: float(r[1]) for r in tushare.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')", (d,)).fetchall()}
    mkt1 = {r[0]: float(r[1]) for r in tushare.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')", (nd,)).fetchall()}
    mkt_rets = [(mkt1[k]/mkt0[k]-1)*100 for k in mkt0 if k in mkt1 and mkt0[k] > 0]
    mkt_ew = float(np.mean(mkt_rets)) if mkt_rets else 0.0

    def stats(lst):
        if not lst:
            return 0.0, 0, 0.0
        rets = [i['ret'] for i in lst]
        return float(np.mean(rets)), len(rets), sum(1 for r in rets if r > 0)/len(rets)

    cmmr_ew, cmmr_n, cmmr_win = stats(cmmr)
    cmmr80_ew, cmmr80_n, _ = stats(cmmr80)
    c80t10_ew, c80t10_n, c80t10_win = stats(top10)
    fsc_ew, fsc_n, fsc_win = stats(fsc)

    return {
        'signal_date': d,
        'cmmr_ew': round(cmmr_ew, 4), 'cmmr_n': cmmr_n, 'cmmr_win': round(cmmr_win, 4),
        'cmmr80_ew': round(cmmr80_ew, 4), 'cmmr80_n': cmmr80_n,
        'cmmr80_top10_ew': round(c80t10_ew, 4),
        'fsc_ew': round(fsc_ew, 4), 'fsc_n': fsc_n, 'fsc_win': round(fsc_win, 4),
        'mkt_ew': round(mkt_ew, 4),
    }

def main():
    state = sqlite3.connect(str(STATE_DB), timeout=30)
    tushare = duckdb.connect(str(TUSHARE_DB), read_only=True)
    ensure_table(state)

    dates = [r[0] for r in state.execute(
        "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]

    written = 0
    for d in dates:
        r = state.execute("SELECT 1 FROM cmmr_backtest WHERE signal_date=?", (d,)).fetchone()
        # 2026-09-11：已有行但新列 cmmr80_top10_ew 为空 → 也重算（历史一次性回填新口径）
        if r and d != dates[-1]:
            have_new = state.execute(
                "SELECT 1 FROM cmmr_backtest WHERE signal_date=? AND cmmr80_top10_ew IS NOT NULL", (d,)).fetchone()
            if have_new:
                continue
        res = compute_day(state, tushare, d)
        if res and res['cmmr_n'] >= 30:
            state.execute("""
                INSERT OR REPLACE INTO cmmr_backtest
                (signal_date, cmmr_ew, cmmr_n, cmmr_win, cmmr80_ew, cmmr80_n, cmmr80_top10_ew, fsc_ew, fsc_n, fsc_win, mkt_ew)
                VALUES (:signal_date, :cmmr_ew, :cmmr_n, :cmmr_win, :cmmr80_ew, :cmmr80_n, :cmmr80_top10_ew, :fsc_ew, :fsc_n, :fsc_win, :mkt_ew)
            """, res)
            written += 1
    state.commit()

    rows = state.execute("""
        SELECT signal_date, cmmr_ew, cmmr_n, cmmr_win, cmmr80_ew, cmmr80_n, fsc_ew, fsc_n, fsc_win, mkt_ew, cmmr80_top10_ew
        FROM cmmr_backtest ORDER BY signal_date
    """).fetchall()
    tushare.close()

    print(f"CMMR 双策略等权回测（新增 {written} 条，累计 {len(rows)} 天）\n")
    print(f"{'信号日':<10}{'CMMR等权':<9}{'CMMR胜率':<8}{'CMMR80':<8}{'CMMR80top10':<12}{'CMMR+等权':<9}{'CMMR+胜率':<9}{'市场':<8}")
    print('-' * 78)
    for r in rows:
        t10 = f"{r[10]:+.2f}%" if r[10] is not None else "  -  "
        print(f"{r[0]:<10}{r[1]:+.2f}%   {r[3]*100:<7.1f}%{r[4]:+.2f}%  {t10:<12}{r[6]:+.2f}%   {r[8]*100:<8.1f}%{r[9]:+.2f}%")

    if rows:
        c_all = [r[1] for r in rows if r[1] is not None]
        f_all = [r[6] for r in rows if r[6] is not None]
        m_all = [r[9] for r in rows if r[9] is not None]
        c80_all = [r[4] for r in rows if r[4] is not None]
        t10_all = [r[10] for r in rows if r[10] is not None]
        day_win_c = sum(1 for r in rows if r[1] > 0) / len(rows)
        day_win_f = sum(1 for r in rows if r[6] > 0) / len(rows)
        print('-' * 78)
        print(f"{'累计':<10}{np.mean(c_all):+.2f}%   {day_win_c*100:<7.1f}%{np.mean(c80_all):+.2f}%  {'':<12}{np.mean(f_all):+.2f}%   {day_win_f*100:<8.1f}%{np.mean(m_all):+.2f}%")
        print(f"\nCMMR 超额(>0全池, vs 市场): {np.mean(c_all)-np.mean(m_all):+.2f}%")
        print(f"CMMR+ 超额( vs 市场): {np.mean(f_all)-np.mean(m_all):+.2f}%")
        print(f"CMMR 高分80子集超额: {np.mean(c80_all)-np.mean(m_all):+.2f}%")
        if t10_all:
            print(f"CMMR80-top10(账户实际选池)超额: {np.mean(t10_all)-np.mean(m_all):+.2f}%  ← 与 cmmr 策略账户同口径")

    state.close()

if __name__ == '__main__':
    main()
