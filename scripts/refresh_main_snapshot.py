#!/usr/bin/env python3
"""收盘后刷新主账户快照（2026-09-17 新增）
=================================================================
动机：主账户账本只在「有成交的执行轮」被 agents/exec_agent.py::sync_to_db 写入 →
      没有成交的日子，holdings.latest_price / account_balance.total_value 就停在上一交易日的价格，
      与面板、报告的「收盘价口径」对不上。
      实测 2026-09-17：MacBook 账本自报 +15.42%（价还是 9/16 收盘）vs 面板 +14.85%（9/17 收盘）；
      M2 侧同源问题（账本 last_update 只在成交日刷新）。

做法：**复用 exec_agent 的同一写入路径**（load_account('main') + sync_to_db(acct, [])，
      results 为空 → 只走「估值 + 持仓/余额落库」分支，绝不产生任何成交），
      再按最新价补算 holdings.pnl / pnl_pct（sync_to_db 不写这两列）。
      机器自适应：M2 主账户在 state.db、MacBook 在 ledger.db（由 core.db / exec_agent 解析）。

cron：17:30 工作日（16:00 的 tushare 增量更新落库之后），只估值不交易。
回滚：删掉 cron + 本脚本即可（不改变任何成交/现金口径，只是把价格刷到最新收盘）。
"""
import sys
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

import datetime  # noqa: E402


def resolve_conn():
    """解析主账户所在库（两机不同）：优先 core.db.connect_ledger，兜底 state.db。"""
    import sqlite3
    try:
        from core.db import connect_ledger
        c = connect_ledger()
        try:
            if c.execute("SELECT 1 FROM account_balance WHERE account_id='main'").fetchone():
                return c, 'core.db.connect_ledger'
        except Exception:
            pass
        c.close()
    except Exception:
        pass
    return sqlite3.connect(str(BASE / 'state.db'), timeout=15), 'state.db(fallback)'


def snap(conn):
    r = conn.execute("SELECT cash_balance, total_value, last_update FROM account_balance "
                     "WHERE account_id='main'").fetchone()
    return r


def main():
    import agents.exec_agent as EA

    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：休市日账户无变动，不刷快照
    from core.trade_calendar import assert_trading_day
    assert_trading_day('主账户快照刷新')

    conn, which = resolve_conn()
    print(f"[refresh] {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  库={which}")
    b = snap(conn)
    print(f"[refresh] 刷新前: 现金 {b[0]:,.2f}  总资产 {b[1]:,.2f}  last_update {b[2]}")

    acct = EA.load_account('main')
    print(f"[refresh] 持仓 {len(acct.positions)} 只  现金 {acct.cash:,.2f}")
    EA.sync_to_db(acct, [])          # 关键：与交易时段完全同一写入路径；results=[] 不产生成交

    # sync_to_db 不写 pnl/pnl_pct → 按最新价补算（持仓页/报告要用）
    n = 0
    for r in conn.execute("SELECT code, shares, avg_cost, latest_price FROM holdings WHERE status='hold'").fetchall():
        sh, ac, lp = float(r[1] or 0), float(r[2] or 0), float(r[3] or 0)
        if not sh or not ac:
            continue
        pnl = (lp - ac) * sh
        conn.execute("UPDATE holdings SET pnl=?, pnl_pct=? WHERE code=?", (round(pnl, 2), round(lp / ac * 100 - 100, 2), r[0]))
        n += 1
    conn.commit()

    a = snap(conn)
    d = (a[1] or 0) - (b[1] or 0)
    print(f"[refresh] 刷新后: 现金 {a[0]:,.2f}  总资产 {a[1]:,.2f}  last_update {a[2]}")
    print(f"[refresh] 总资产变动 {d:+,.2f}（= 持仓按最新收盘价重估）  pnl 已补算 {n} 只")
    lp_stale = conn.execute("SELECT COUNT(*) FROM holdings WHERE status='hold' AND (latest_price IS NULL OR latest_price=0)").fetchone()[0]
    if lp_stale:
        print(f"[refresh] ⚠️ {lp_stale} 只持仓无最新价（用成本兜底）")
    conn.close()


if __name__ == '__main__':
    main()
