#!/usr/bin/env python3
"""补记策略账户 2026-08-03 首日建仓交易流水（一次性）。

背景：strategy_accounts_daily.py 8/3 首笔成交时未写 acct.trades / trade_log，
导致三账户 json.trades 为空、面板交易流水无记录。
本脚本从现有 positions（buy_date=20260803, avg_cost=成交实时价）反推买入记录，
写入：① sim_accounts/<id>.json.trades（AccountStore 原生）② state.db.trade_log（strategy=账户id）。
幂等：已存在同代码同日买入记录则跳过。
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from core.unified_account import AccountStore, Trade

STATE_DB = _SCRIPT_DIR / 'state.db'
TRADE_DATE = '20260803'
TRADE_DATE_DISPLAY = '2026-08-03'
# 首日建仓时点：8/3 09:30 cron 首次触发（sim_accounts 目录 mtime 09:30 佐证），秒级不可考，近似值
TRADE_TIME = '09:30:00'
ACCOUNTS = {'fusion3f': '三因子融合', 'cmmr': 'CMMR独立', 'cmmr_fusion': 'CMMR+融合'}


def main():
    store = AccountStore()
    state = sqlite3.connect(str(STATE_DB), timeout=30)
    total = 0
    for aid, name in ACCOUNTS.items():
        acct = store.load(aid)
        existing = {(t.code, t.date.replace('-', '')) for t in acct.trades}
        n = 0
        for p in acct.positions:
            amt = round(p.shares * p.avg_cost, 2)
            # ① trade_log 幂等补插（json 有记录但 trade_log 可能被 exec_agent 清过）
            dup = state.execute(
                "SELECT COUNT(*) FROM trade_log WHERE strategy=? AND code=? AND trade_date=?",
                (aid, p.code, TRADE_DATE_DISPLAY)).fetchone()[0]
            if not dup:
                state.execute("""
                    INSERT INTO trade_log
                    (code, name, direction, price, quantity, amount, trade_date, trade_time,
                     strategy, signal_score, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (p.code, p.name or '', 'BUY', round(p.avg_cost, 4), p.shares,
                      round(amt, 4), TRADE_DATE_DISPLAY, TRADE_TIME,
                      aid, None, '策略模拟账户(补记)'))
                n += 1
            else:
                # 已存在：修正 trade_time（首日建仓时点=9:30 首次 cron 触发近似）
                state.execute(
                    "UPDATE trade_log SET trade_time=? WHERE strategy=? AND code=? AND trade_date=?",
                    (TRADE_TIME, aid, p.code, TRADE_DATE_DISPLAY))
            # ② json.trades 幂等补记
            if (p.code, TRADE_DATE) not in existing:
                acct.trades.append(Trade(
                    date=TRADE_DATE_DISPLAY, action='买入', code=p.code,
                    name=p.name or '', price=p.avg_cost, shares=p.shares,
                    amount=amt, reason='首日建仓', trade_time=TRADE_TIME))
                n += 1
            else:
                # 已存在：补 trade_time（旧记录无时间字段）
                for t in acct.trades:
                    if t.code == p.code and t.date.replace('-', '') == TRADE_DATE and not t.trade_time:
                        t.trade_time = TRADE_TIME
        store.save(acct)
        total += n
        print(f"{name}({aid}): 补记 {n} 笔买入，当前持仓 {len(acct.positions)} 只")
    state.commit()
    state.close()
    print(f"共补记 {total} 笔")


if __name__ == '__main__':
    main()
