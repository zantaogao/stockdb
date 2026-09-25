#!/usr/bin/env python3
"""给 MacBook 已销户账户 fusion3f / fusion_dual 补 2026-09-16「清算 NAV 行」。
（只动这两户、只加一行；幂等 INSERT OR REPLACE，写前整库快照备份）

背景：两户 2026-09-11 销户（strategy_accounts_daily.py closed=True → NAV 停止落库），
但 9/16 手动碎仓脚本仍直写 DB（卖出 5/12 笔、positions 23→18 / 32→20、meta.cash 8,658 / 249,623），
NAV 表最后一行停留在 20260910（n_pos 23/32）→ 面板卡片 nav/现金/持仓数 与 下方持仓列表打架。
本脚本按日更脚本同一写法补一行 20260916：nav = cash + Σ(持仓×9/16收盘)，n_pos = 实际持仓数。

用法：
  python3 -B add_liquidation_nav_row.py            # dry-run（只打印）
  python3 -B add_liquidation_nav_row.py --apply    # 写库（先备份）
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import sys

import duckdb

BASE = os.path.expanduser('~/.hermes/stockdb')
LEDGER = os.path.join(BASE, 'ledger.db')
DUCK = os.path.join(BASE, 'tushare.db')
BAKDIR = os.path.join(BASE, 'db_backups', 'manual')
ROW_DATE = '20260916'
TARGETS = ('fusion3f', 'fusion_dual')
BENCH = '000852'          # 中证1000：strategy_accounts_daily 的 market_ret 口径
INIT_CAPITAL = 1_000_000.0


def ts(code):
    return code + ('.SH' if code[0] in '69' else '.SZ')


def build():
    conn = sqlite3.connect(LEDGER)
    conn.row_factory = sqlite3.Row
    duck = duckdb.connect(DUCK, read_only=True, config={'memory_limit': '1GB', 'threads': '2'})
    plan = {}
    try:
        for aid in TARGETS:
            m = conn.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchone()
            if not m:
                raise SystemExit(f'{aid} 无 meta 行，中止')
            cash = round(float(m['cash']), 2)
            pos = conn.execute("SELECT code, shares, avg_cost FROM strategy_positions "
                               "WHERE account_id=? ORDER BY code", (aid,)).fetchall()
            if not pos:
                raise SystemExit(f'{aid} 无持仓行，中止')
            prev = conn.execute("SELECT date, nav FROM strategy_accounts_legacy WHERE account_id=? AND date<? "
                                "ORDER BY date DESC LIMIT 1", (aid, ROW_DATE)).fetchone()
            cur = conn.execute("SELECT nav FROM strategy_accounts_legacy WHERE account_id=? AND date=?",
                               (aid, ROW_DATE)).fetchone()
            q = ','.join("'%s'" % ts(r['code']) for r in pos)
            px = {t[:6]: float(cl) for t, cl in duck.execute(
                f"SELECT ts_code, close FROM daily WHERE trade_date='{ROW_DATE}' AND ts_code IN ({q})").fetchall()}
            miss = [r['code'] for r in pos if r['code'] not in px]
            pv = round(sum(int(r['shares']) * px.get(r['code'], float(r['avg_cost'])) for r in pos), 2)
            nav = round(cash + pv, 2)
            dret = round((nav / float(prev['nav']) - 1) * 100, 4) if prev and prev['nav'] else 0.0
            # 基准窗口收益（最后一行日期 → 9/16），与 daily_ret 同窗口
            b0, b1 = None, None
            if prev:
                bd = f"{prev['date'][:4]}-{prev['date'][4:6]}-{prev['date'][6:]}"
                e = f"{ROW_DATE[:4]}-{ROW_DATE[4:6]}-{ROW_DATE[6:]}"
                r0 = duck.execute("SELECT close FROM index_daily WHERE index_code=? AND date=CAST(? AS DATE)", (BENCH, bd)).fetchone()
                r1 = duck.execute("SELECT close FROM index_daily WHERE index_code=? AND date=CAST(? AS DATE)", (BENCH, e)).fetchone()
                b0 = float(r0[0]) if r0 else None
                b1 = float(r1[0]) if r1 else None
            mret = round((b1 / b0 - 1) * 100, 4) if (b0 and b1) else 0.0
            plan[aid] = dict(cash=cash, pv=pv, nav=nav, n_pos=len(pos), dret=dret, mret=mret,
                             prev=dict(prev) if prev else None, exists=dict(cur) if cur else None,
                             miss=miss, bench=(b0, b1))
        return plan
    finally:
        duck.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    plan = build()

    print(f"══ 计划写入 strategy_accounts_legacy 行：date={ROW_DATE} ══")
    for aid, p in plan.items():
        print(f"\n[{aid}]")
        print(f"  meta.cash            = {p['cash']:,.2f}")
        print(f"  pos_value(9/16收盘)   = {p['pv']:,.2f}   n_pos={p['n_pos']}")
        print(f"  nav                  = {p['nav']:,.2f}   累计={p['nav'] / INIT_CAPITAL - 1:+.2%}")
        print(f"  上一行               = {p['prev']}")
        print(f"  daily_ret(窗口)      = {p['dret']:+.4f}%")
        print(f"  market_ret(中证1000窗口) = {p['mret']:+.4f}%   ({p['bench']})")
        print(f"  当前是否已有该行     = {p['exists']}")
        if p['miss']:
            print(f"  ⚠️ 缺收盘价（用成本兜底）: {p['miss']}")

    if not a.apply:
        print("\n[dry-run] 未写库。加 --apply 执行。")
        return

    os.makedirs(BAKDIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(BAKDIR, f'ledger.db.{stamp}.navrow.bak')
    src = sqlite3.connect(LEDGER)
    dst = sqlite3.connect(bak)
    with dst:
        src.backup(dst)          # 一致性快照（WAL 安全）
    dst.close()
    src.close()
    print(f"\n[备份] {bak}  ({os.path.getsize(bak) / 1e6:.1f} MB)")

    conn = sqlite3.connect(LEDGER)
    try:
        for aid, p in plan.items():
            conn.execute(
                "INSERT OR REPLACE INTO strategy_accounts_legacy "
                "(account_id, date, nav, cash, pos_value, daily_ret, market_ret, n_pos) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (aid, ROW_DATE, p['nav'], p['cash'], p['pv'], p['dret'], p['mret'], p['n_pos']))
        conn.commit()
        print("\n[写入完成] 读回校验：")
        ok = True
        for aid, p in plan.items():
            r = conn.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,market_ret,n_pos "
                             "FROM strategy_accounts_legacy WHERE account_id=? AND date=?",
                             (aid, ROW_DATE)).fetchone()
            n = conn.execute("SELECT COUNT(*) FROM strategy_positions WHERE account_id=?", (aid,)).fetchone()[0]
            good = (abs(r[2] - (r[3] + r[4])) < 0.01 and r[7] == n and abs(r[2] - p['nav']) < 0.01)
            ok &= good
            print(f"  {aid}: nav={r[2]:,.2f} cash={r[3]:,.2f} pos_value={r[4]:,.2f} "
                  f"daily_ret={r[5]:+.4f}% market_ret={r[6]:+.4f}% n_pos={r[7]}(持仓表{n}) "
                  f"{'✓' if good else '✗'}")
            top = conn.execute("SELECT MAX(date) FROM strategy_accounts WHERE account_id=?", (aid,)).fetchone()[0]
            print(f"     视图 strategy_accounts 最后日期 = {top}")
        if not ok:
            print("\n❌ 校验失败，请人工检查（备份可用于回滚）")
            sys.exit(1)
    finally:
        conn.close()
    print("\n✅ 两行已写入并通过读回校验")


if __name__ == '__main__':
    main()
