#!/usr/bin/env python3
"""三因子强买等权回测（cron 版）
每日运行：对所有有次日数据的信号日计算 T+1 收益并持久化到 state.db。
- 表: fusion_3f_backtest (signal_date 主键, 幂等)
- 输出: 最新记录 + 累计汇总
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
        CREATE TABLE IF NOT EXISTS fusion_3f_backtest (
            signal_date TEXT PRIMARY KEY,
            sb_ew REAL, sb_win REAL, n_sb INTEGER,
            mkt_ew REAL, ss_ew REAL, n_ss INTEGER,
            top10_ew REAL, top10_win REAL,
            ls_ret REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

def compute_day(state, tushare, d):
    """计算单日回测，返回 dict 或 None"""
    nd = tushare.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", (d,)).fetchone()[0]
    if not nd:
        return None

    rows = state.execute(
        "SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals WHERE REPLACE(date,'-','')=?", (d,)).fetchall()
    if not rows:
        return None

    ts_list = [ts_code(r[0]) for r in rows]
    ph = ','.join(['?']*len(ts_list))
    p0 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (d,)+tuple(ts_list)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (nd,)+tuple(ts_list)).fetchall()}

    items = []
    for code, score, sig in rows:
        ts = ts_code(code)
        if ts in p0 and ts in p1 and p0[ts] > 0:
            items.append({'code': code, 'score': float(score), 'sig': sig,
                          'ret': (p1[ts]/p0[ts]-1)*100})
    if not items:
        return None

    sb = [i for i in items if i['sig'] == '强买']
    ss = [i for i in items if i['sig'] == '强卖']
    if not sb:
        return None

    sb_rets = [i['ret'] for i in sb]
    ss_rets = [i['ret'] for i in ss]
    sb_ew = float(np.mean(sb_rets))
    sb_win = sum(1 for r in sb_rets if r > 0) / len(sb_rets)

    # 全市场等权（同一天所有有价格的票）
    mkt0 = {r[0]: float(r[1]) for r in tushare.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')", (d,)).fetchall()}
    mkt1 = {r[0]: float(r[1]) for r in tushare.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')", (nd,)).fetchall()}
    mkt_rets = [(mkt1[k]/mkt0[k]-1)*100 for k in mkt0 if k in mkt1 and mkt0[k] > 0]
    mkt_ew = float(np.mean(mkt_rets)) if mkt_rets else 0.0

    # Top10% 精选
    sb_sorted = sorted(sb, key=lambda x: x['score'], reverse=True)
    n_top = max(1, len(sb_sorted) // 10)
    top = sb_sorted[:n_top]
    top10_ew = float(np.mean([i['ret'] for i in top]))
    top10_win = sum(1 for i in top if i['ret'] > 0) / len(top)

    ss_ew = float(np.mean(ss_rets)) if ss_rets else 0.0
    ls_ret = sb_ew - ss_ew if ss_rets else 0.0

    return {
        'signal_date': d,
        'sb_ew': round(sb_ew, 4), 'sb_win': round(sb_win, 4), 'n_sb': len(sb_rets),
        'mkt_ew': round(mkt_ew, 4),
        'ss_ew': round(ss_ew, 4), 'n_ss': len(ss_rets),
        'top10_ew': round(top10_ew, 4), 'top10_win': round(top10_win, 4),
        'ls_ret': round(ls_ret, 4),
    }

def main():
    state = sqlite3.connect(str(STATE_DB), timeout=30)
    tushare = duckdb.connect(str(TUSHARE_DB), read_only=True)
    ensure_table(state)

    # 所有信号日（含历史）
    dates = [r[0] for r in state.execute(
        "SELECT DISTINCT REPLACE(date,'-','') FROM fusion_3f_signals ORDER BY 1").fetchall()]

    written = 0
    for d in dates:
        # 已有记录且当日数据不会再变（非最新信号日）则跳过；最新日允许重算（次日可能刚到位）
        r = state.execute("SELECT 1 FROM fusion_3f_backtest WHERE signal_date=?", (d,)).fetchone()
        if r and d != dates[-1]:
            continue
        res = compute_day(state, tushare, d)
        if res:
            state.execute("""
                INSERT OR REPLACE INTO fusion_3f_backtest
                (signal_date, sb_ew, sb_win, n_sb, mkt_ew, ss_ew, n_ss, top10_ew, top10_win, ls_ret)
                VALUES (:signal_date, :sb_ew, :sb_win, :n_sb, :mkt_ew, :ss_ew, :n_ss, :top10_ew, :top10_win, :ls_ret)
            """, res)
            written += 1
    state.commit()

    # 输出汇总
    rows = state.execute("""
        SELECT signal_date, sb_ew, sb_win, n_sb, mkt_ew, ss_ew, top10_ew, top10_win, ls_ret
        FROM fusion_3f_backtest ORDER BY signal_date
    """).fetchall()
    tushare.close()

    print(f"三因子强买等权回测（新增 {written} 条，累计 {len(rows)} 天）\n")
    print(f"{'信号日':<10}{'强买等权':<9}{'强买胜率':<8}{'市场':<8}{'强卖':<8}{'Top10%':<8}{'多空':<8}")
    print('-' * 62)
    for r in rows:
        print(f"{r[0]:<10}{r[1]:+.2f}%   {r[2]*100:<7.1f}%{r[4]:+.2f}%  {r[5]:+.2f}%  {r[6]:+.2f}%  {r[8]:+.2f}%")

    if rows:
        sb_all = [r[1] for r in rows if r[1] is not None]
        mkt_all = [r[4] for r in rows if r[4] is not None]
        ss_all = [r[5] for r in rows if r[5] is not None]
        top_all = [r[6] for r in rows if r[6] is not None]
        ls_all = [r[8] for r in rows if r[8] is not None]
        # 按天胜率：当天强买等权收益 > 0 的天数占比
        day_win = sum(1 for r in rows if r[1] > 0) / len(rows)
        print('-' * 62)
        print(f"{'累计':<10}{np.mean(sb_all):+.2f}%   {day_win*100:<7.1f}%{np.mean(mkt_all):+.2f}%  {np.mean(ss_all):+.2f}%  {np.mean(top_all):+.2f}%  {np.mean(ls_all):+.2f}%")
        print(f"\n强买超额(强买-市场): {np.mean(sb_all)-np.mean(mkt_all):+.2f}%  (按天胜率 {day_win*100:.0f}%)")
        print(f"分数精选超额(Top10%-等权): {np.mean(top_all)-np.mean(sb_all):+.2f}%")

    state.close()

if __name__ == '__main__':
    main()
