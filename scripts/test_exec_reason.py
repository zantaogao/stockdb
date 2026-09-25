#!/usr/bin/env python3
"""单测：主账户成交原因落库 + execution_logs 埋点（2026-09-11 修复）

背景（审计发现）：trade_log 主账户 SELL 的 notes 全是 'auto_sync'/'backfill'，execution_logs 是空表
→ 主账户每笔卖出无法归因。修复：sync_to_db 把 pending 订单的 reason 写进 notes，并补 execution_logs。

运行：cd ~/.hermes/stockdb && python3 -B scripts/test_exec_reason.py
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BASE))
sys.path.insert(0, str(_BASE / 'agents'))

import exec_agent as E
from core.unified_account import Account, Position

DDL = """
CREATE TABLE holdings (code TEXT, name TEXT, status TEXT, buy_date TEXT, avg_cost REAL, shares INTEGER,
                       latest_price REAL, update_time TEXT, target_price REAL, stop_loss REAL);
CREATE TABLE position_peaks (code TEXT PRIMARY KEY, peak_price REAL, updated_at TEXT);
CREATE TABLE trade_log (id INTEGER, code TEXT, name TEXT, direction TEXT, quantity INTEGER, price REAL,
                        amount REAL, trade_date TEXT, trade_time TEXT, strategy TEXT, notes TEXT);
CREATE TABLE account_balance (account_id TEXT, account_name TEXT, initial_capital REAL, cash_balance REAL,
                              total_value REAL, last_update TEXT);
CREATE TABLE execution_logs (exec_id TEXT, signal_id TEXT, ts_code TEXT, direction TEXT, exec_price REAL,
                             exec_quantity INTEGER, exec_time TEXT, status TEXT, error_msg TEXT);
"""


class TestExecReason(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        # M2=state.db / MacBook=ledger.db（v2 热层）都要建，保证两机通用
        for fn in ('state.db', 'ledger.db'):
            conn = sqlite3.connect(str(base / fn))
            conn.executescript(DDL)
            conn.commit()
            conn.close()
        self._orig_base = E.BASE
        E.BASE = base          # sync_to_db 内部用 BASE/'state.db'
        # MacBook 版 sync_to_db 走 connect_ledger()（不经 BASE）→ 一并重定向
        self._orig_cl = getattr(E, 'connect_ledger', None)
        if self._orig_cl is not None:
            E.connect_ledger = lambda: sqlite3.connect(str(base / 'ledger.db'))
        # 🛡️ 硬护栏（2026-09-11 事故后加）：本测试期间任何打开真实 state.db/ledger.db 的尝试直接抛错。
        #    事故：MacBook 版 sync_to_db 用 connect_ledger() 绕过 BASE 补丁 → 测试写进生产 ledger.db
        #    （holdings/position_peaks 被清空，已用 9/10 备份还原）。这道护栏机器无关，防复发。
        self._orig_connect = sqlite3.connect
        guard = str(base)
        def _guarded(path, *a, **k):
            pth = str(path)
            if pth.endswith(('state.db', 'ledger.db')) and guard not in pth:
                raise AssertionError(f'测试禁止打开生产库: {pth}')
            return self._orig_connect(path, *a, **k)
        sqlite3.connect = _guarded

    def tearDown(self):
        sqlite3.connect = self._orig_connect
        E.BASE = self._orig_base
        if self._orig_cl is not None:
            E.connect_ledger = self._orig_cl
        self.tmp.cleanup()

    def _db(self):
        """读回校验用的连接：M2 写 state.db / MacBook 写 ledger.db（v2 热层），自动取有数据那个"""
        for fn in ('state.db', 'ledger.db'):
            conn = sqlite3.connect(str(Path(self.tmp.name) / fn))
            if conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0] > 0:
                return conn
        return sqlite3.connect(str(Path(self.tmp.name) / 'state.db'))

    def _acct(self):
        acct = Account('main', '中长线', 1_000_000.0)
        acct.cash = 500_000.0
        acct.positions = [Position(code='600000', name='测试股', shares=1000, avg_cost=10.0,
                                   buy_date='2026-09-01', peak_price=11.0, stop_loss=8.8, target=12.0)]
        return acct

    def test_reason_written_to_trade_log_and_execution_logs(self):
        results = [
            {'action': 'SELL', 'stock_code': '600000', 'stock_name': '测试股', 'price': 12.5,
             'shares': 1000, 'status': 'EXECUTED', 'reason': '回撤止盈(峰值12.80,大盘-2.3%)',
             'revenue': 12500.0},
            {'action': 'BUY', 'stock_code': '000001', 'stock_name': '平安银行', 'price': 11.0,
             'shares': 2000, 'status': 'EXECUTED', 'reason': '评分86 中置信', 'total_cost': 22000.0},
            {'action': 'BUY', 'stock_code': '300750', 'stock_name': '宁德时代', 'price': 200.0,
             'shares': 100, 'status': 'FAILED', 'reason': '评分78', 'error': '300 科创/创业板 100股<200 最低申报，废单拦截'},
        ]
        acct = self._acct()
        acct.positions = []          # 卖出已在执行阶段从账户移除
        E.sync_to_db(acct, results)

        conn = self._db()
        rows = dict((r[0] + r[1], r[2]) for r in
                    conn.execute("SELECT code, direction, notes FROM trade_log WHERE strategy='main'"))
        self.assertIn('回撤止盈', rows.get('600000SELL', ''), f'卖出原因未落库: {rows}')
        self.assertIn('评分86', rows.get('000001BUY', ''), f'买入原因未落库: {rows}')
        self.assertNotEqual(rows.get('000001BUY'), 'auto_sync')

        ex = conn.execute("SELECT exec_id, ts_code, direction, status, error_msg FROM execution_logs "
                          "ORDER BY ts_code").fetchall()
        self.assertEqual(len(ex), 3, f'execution_logs 应记录 3 笔（含废单），实际 {ex}')
        by_code = {r[1]: r for r in ex}
        self.assertEqual(by_code['600000'][3], 'EXECUTED')
        self.assertEqual(by_code['300750'][3], 'FAILED')
        self.assertIn('废单拦截', by_code['300750'][4] or '')
        conn.close()

    def test_notes_fallback_auto_sync_when_no_reason(self):
        """没带 reason 的订单仍写 'auto_sync'（不破坏老口径）"""
        results = [{'action': 'BUY', 'stock_code': '000002', 'stock_name': '万科A', 'price': 9.0,
                    'shares': 100, 'status': 'EXECUTED', 'total_cost': 900.0}]
        acct = self._acct()
        acct.positions = []
        E.sync_to_db(acct, results)
        conn = self._db()
        r = conn.execute("SELECT notes FROM trade_log WHERE code='000002'").fetchone()
        self.assertEqual(r[0], 'auto_sync')
        conn.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
