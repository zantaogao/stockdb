#!/usr/bin/env python3
"""strategy_accounts_daily 重评日重建语义单测（2026-09-02 用户拍板：废除无脑清仓）。

覆盖场景（对照 9/2 实盘案例）：
  1. 中岩大地型：到期且仍在 top10 → 保留 + 补差到等权（不卖旧开新空转）
  2. 荣信文化型：窗口期内 top-up 刚买的仓（买入日 > 上次重评日）→ 信号未过期，重评日不清
  3. 到期且不在 top10 → 窗口到期重建卖出（不进冷却）
  4. 重评日硬止损（在 top10 内也卖）→ 进冷却 → 同日不得买回
  5. 全局冷却（600363 型跨账户记录）→ 保留仓补差被拦（不加仓）
  6. memory 状态（时间腿已清）价格/模型腿全过 → 允许买回并删记录
  7. T+1：今日买入的仓任何情况不可当日卖
  8. R7 观察窗：已持有且浮亏 ≤-6% → 不加仓（等尾盘裁决）
  9. 大跌市：重评日停买保留现金（卖出照常），last_re 不推进
  10. 非重评日：topup='all'（旧口径）只买缺失目标；topup='gap'（新默认）只补已持有目标仓
      + 重评日碎仓清理（权重<1% 且不在新 top10 → 卖）
运行：cd ~/.hermes/stockdb && python3 -B scripts/test_rebalance_semantics.py
"""
import os
import sqlite3
import sys
import unittest
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BASE))
sys.path.insert(0, str(_BASE / 'scripts'))

import strategy_accounts_daily as S
import cooldown
from core.unified_account import Account, Position, Trade

INIT = S.INIT_CAPITAL
LAST_RE = '20260818'   # 上次重评日：buy_date ≤ 它 = 满窗口旧仓
TODAY = '20260902'

# 新 top10 目标（9/1 信号，分数序）——含 8/18 旧仓重叠票
TARGETS = [
    ('003001', 124.80), ('300753', 123.89), ('600833', 123.63),
    ('300937', 123.37), ('301166', 123.10), ('603331', 122.98),
    ('300942', 122.07), ('003013', 121.68),
]
TARGET_CODES = {c for c, _ in TARGETS}

# 实时价（与 9/2 实盘一致）
PRICES = {
    '003001': 16.28, '300753': 22.74, '600833': 11.05, '300937': 25.80,
    '301166': 29.36, '603331': 12.67, '300942': 6.72, '003013': 15.90,
    '002879': 16.51, '688004': 23.18, '300364': 27.80,
    '600363': 16.50, '688191': 20.22,
}
NAMES = {'003001': '中岩大地', '300753': '爱朋医疗', '600833': '第一医药',
         '300937': '药易购', '301166': '优宁维', '603331': '百达精工',
         '300942': '易瑞生物', '003013': '地铁设计', '002879': '长缆科技',
         '688004': '博汇科技', '300364': '中文在线', '600363': '联创光电',
         '688191': '智洋创新'}


class FakeTushare:
    """假 tushare：提供 daily 交易日序列 / 昨收 / 名称 / 指数（非下跌趋势）"""
    def __init__(self, trading_days, latest_daily=None, closes=None):
        self.trading_days = trading_days
        self.latest = latest_daily or max(trading_days)
        self.closes = closes or {}
        self.index_closes = [(self.latest, 100.0), ('20260901', 101.5), ('20260831', 102.0)]

    def execute(self, sql, params=None):
        params = params or ()
        s = ' '.join(str(sql).split())
        if 'COUNT(DISTINCT trade_date)' in s:
            n = sum(1 for d in self.trading_days if d > str(params[0]))
            return _Rows([(n,)])
        if 'MAX(trade_date)' in s:
            return _Rows([(self.latest,)])
        if 'SELECT name FROM stock_basic' in s:
            code = str(params[0]).split('.')[0]
            return _Rows([(NAMES.get(code, code),)])
        if 'index_daily_raw' in s:
            return _Rows(self.index_closes)
        if 'ts_code, close FROM daily' in s:
            return _Rows([(f'{c}.SH', v) for c, v in self.closes.items()])
        raise AssertionError(f'FakeTushare 未处理 SQL: {s}')


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeStore:
    def __init__(self, acct):
        self.acct = acct
        self.saves = []

    def load(self, account_id):
        return self.acct

    def save(self, acct):
        self.saves.append(acct)


def make_state():
    conn = sqlite3.connect(':memory:')
    S.ensure_nav_table(conn)
    cooldown.ensure_table(conn)
    cooldown.ensure_tp_ban_table(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS trade_log (
        id INTEGER, code TEXT, name TEXT, direction TEXT, price REAL,
        quantity INTEGER, amount REAL, trade_date TEXT, trade_time TEXT,
        strategy TEXT, signal_score REAL, notes TEXT)""")
    # count_signal_days_since 用的信号日表（主账户时间腿）
    conn.execute("CREATE TABLE IF NOT EXISTS signal_history (date TEXT, stock_code TEXT, cmmr_score REAL)")
    conn.execute("INSERT OR REPLACE INTO signal_history (date, stock_code) VALUES ('20260901','000001'),('20260902','000001')")
    conn.commit()
    return conn


def make_acct(aid='cmmr_fusion', positions=None, cash=INIT, cfg=None):
    cfg = dict(cfg or {})
    cfg.setdefault('last_rebalance_date', LAST_RE)
    acct = Account(aid, 'CMMR+融合', INIT, config=cfg, positions=list(positions or []))
    acct.cash = cash
    return acct


def pos(code, shares, cost, buy_date):
    return Position(code=code, name=NAMES.get(code, code), shares=shares,
                    avg_cost=cost, buy_date=buy_date, peak_price=cost)


def trade_days_after_last_re():
    # 8/18 之后到 9/2 的完整交易日序列（is_re 判定用）
    return ['20260819', '20260820', '20260821', '20260824', '20260825',
            '20260826', '20260827', '20260828', '20260831', '20260901']


class Base(unittest.TestCase):
    def setUp(self):
        self._prices = dict(PRICES)
        self._open_px = None            # None = 拿不到开盘价（走 14:30 尾盘确认）
        self._orig_fetch_batch = S.fetch_prices_batch
        self._orig_fetch_open = S.fetch_price_open
        self._orig_fetch_live = S.fetch_price_live
        self._orig_targets = S.get_signal_targets
        self._orig_popen = S.subprocess.Popen
        self._orig_crash = S.is_crash_market
        S.fetch_prices_batch = self._fake_batch
        S.fetch_price_open = lambda code: self._open_px
        S.fetch_price_live = lambda code: (1000.0, 0.0)
        S.get_signal_targets = lambda *a, **k: TARGETS
        S.subprocess.Popen = lambda *a, **k: None
        S.is_crash_market = lambda *a, **k: (False, '')
        S.STOP_CONFIRM_TIME = '23:59'   # 测试默认避开 14:30 尾盘分支

    def tearDown(self):
        S.fetch_prices_batch = self._orig_fetch_batch
        S.fetch_price_open = self._orig_fetch_open
        S.fetch_price_live = self._orig_fetch_live
        S.get_signal_targets = self._orig_targets
        S.subprocess.Popen = self._orig_popen
        S.is_crash_market = self._orig_crash
        S.STOP_CONFIRM_TIME = '14:30'

    def _fake_batch(self, codes):
        return {c: self._prices[c] for c in codes if c in self._prices}

    def run_re(self, acct, cash=None, trade_date=TODAY, state=None, tushare=None):
        """跑一轮 run_day（重评日），返回 (account, state)。跨天场景可传同一 state/tushare"""
        if cash is not None:
            acct.cash = cash
        if state is None:
            state = make_state()
        if tushare is None:
            tushare = FakeTushare(trade_days_after_last_re(), latest_daily='20260901', closes=self._prices)
        store = FakeStore(acct)
        S.run_day(store, state, tushare, '20260901', trade_date, acct.id, set(), 0.0)
        return acct, state


# ─────────────────────────────────────────────────────────
class TestReevalSemantics(Base):
    """S1: 中岩大地型——到期且在 top10：保留+补差；到期不在 top10：重建卖出；
    未到期（9/1 刚买）无论是否在 top10 都保留；无任何同 tick 卖买同一只"""

    def test_overlap_rebuilt_without_churn(self):
        positions = [
            pos('003001', 3800, 15.81, LAST_RE),    # 到期 & 在 top10 → 保留+补差
            pos('300937', 2500, 24.25, LAST_RE),    # 到期 & 在 top10
            pos('600833', 5600, 10.72, LAST_RE),    # 到期 & 在 top10
            pos('603331', 4800, 12.65, LAST_RE),    # 到期 & 在 top10
            pos('002879', 8000, 16.61, LAST_RE),    # 到期 & 不在 top10 → 卖（重建）
            pos('688004', 800, 22.61, '20260901'),  # 未到期 & 不在 top10 → 保留（真实权重 1.4%）
            pos('300753', 800, 21.77, '20260901'),  # 未到期 & 在 top10 → 保留+补差
            pos('003013', 1000, 15.71, '20260901'),  # 未到期 & 在 top10 → 保留+补差
        ]
        acct = make_acct(positions=positions)
        # 让现金 ≈ 真实 NAV 结构（总资产 ~130 万）
        acct, _ = self.run_re(acct, cash=854_000.0)

        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        buys = [t for t in acct.trades if t.action == '买入' and t.date == TODAY]
        sold_codes = {t.code for t in sells}
        bought_codes = {t.code for t in buys}

        # 1) 只卖了到期且不在 top10 的 002879，reason=窗口到期重建（不进冷却）
        self.assertEqual(sold_codes, {'002879'}, f'卖出集合不对: {sold_codes}')
        self.assertEqual(sells[0].reason, '窗口到期重建')

        # 2) 无任何同 tick 卖出又买入同一只（核心回归：9/2 实盘 8 对空转）
        self.assertEqual(sold_codes & bought_codes, set(),
                         f'同日卖出又买入同一只: {sold_codes & bought_codes}')

        # 3) 未到期刚买的 688004（不在 top10，权重 1.4%>1%）保留，一股未卖
        kp = acct.get_position('688004')
        self.assertIsNotNone(kp)
        self.assertEqual(kp.shares, 800)

        # 4) 8 个目标全部在持仓；003001 补差后 ≈ per_target 等权（不再卖3800买10000 空转）
        codes_now = {p.code for p in acct.positions}
        self.assertTrue(TARGET_CODES.issubset(codes_now), f'缺目标: {TARGET_CODES - codes_now}')
        pj = acct.get_position('003001')
        self.assertIsNotNone(pj, '003001 应保留（不再清仓重开）')
        self.assertGreater(pj.shares, 3800, '003001 应被补差到等权')
        per = (acct.cash + sum(p.shares * self._prices[p.code] for p in acct.positions
                               if p.code in TARGET_CODES)) / len(TARGET_CODES)
        for code in TARGET_CODES:
            p = acct.get_position(code)
            self.assertIsNotNone(p)
            val = p.shares * self._prices[code]
            self.assertLessEqual(abs(val - per) / per, 0.02, f'{code} 偏离等权 {val} vs {per}')

        # 5) 加仓补差与新建仓都走 trade_log 的 BUY + reason 语义
        reasons = {t.reason for t in buys}
        self.assertTrue(reasons <= {'重评补差至等权', '重评等权建仓'}, reasons)

        # 6) NAV 守恒（±1% 内，模拟盘无摩擦）
        nav = acct.cash + sum(p.shares * self._prices[p.code] for p in acct.positions)
        self.assertAlmostEqual(nav / 1_300_000.0, 1.0, delta=0.01, msg=f'NAV={nav}')

        # 7) 重评日标记推进
        self.assertEqual(acct.config.get('last_rebalance_date'), TODAY)

    def test_straggler_bought_day_before_reeval_kept(self):
        """S2 荣信文化型：9/1 刚 top-up（未到期）且已掉出新 top10 → 保留，不割 1 天仓"""
        positions = [
            pos('300364', 1500, 29.00, '20260901'),  # 未到期、不在 top10、现 -4.1%（实盘荣信文化同构）
            pos('002879', 8000, 16.61, LAST_RE),     # 到期 & 不在 top10 → 卖
        ]
        acct = make_acct(positions=positions)
        acct, _ = self.run_re(acct, cash=1_000_000.0)

        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        sold_codes = {t.code for t in sells}
        self.assertEqual(sold_codes, {'002879'})
        self.assertIsNotNone(acct.get_position('300364'), '9/1 刚买的仓不得被重评日清掉')
        # 8 个目标照常建仓（新 top10 与旧仓无重叠）
        for code in TARGET_CODES:
            self.assertIsNotNone(acct.get_position(code), f'{code} 应被建仓')


class TestRiskRedlineOnReeval(Base):
    """S3/S8: 重评日风控红线仍然生效"""

    def test_hard_stop_in_target_sold_and_cooldown_blocks_same_day_rebuy(self):
        positions = [
            pos('600363', 6700, 16.32, LAST_RE),     # 到期 & 在 top10，但现价 -15%（硬止损）
        ]
        self._prices['600363'] = 13.9               # ≤ 16.32×0.88=14.36
        TARGETS_HAS_600363 = TARGETS + [('600363', 120.0)]
        S.get_signal_targets = lambda *a, **k: TARGETS_HAS_600363
        try:
            acct = make_acct(positions=positions)
            acct, state = self.run_re(acct, cash=900_000.0)
        finally:
            S.get_signal_targets = lambda *a, **k: TARGETS

        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0].code, '600363')
        self.assertEqual(sells[0].reason, '硬止损-12%')
        # 冷却记录存在且状态仍是 cooldown（清腿在卖出前执行 → 今日止损时间腿保留）
        row = state.execute("SELECT status FROM trade_cooldown WHERE code='600363' AND strategy='cmmr_fusion'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'cooldown')
        # 同日不得买回（600363 不在最终持仓）
        self.assertIsNone(acct.get_position('600363'))
        buys = [t for t in acct.trades if t.action == '买入' and t.date == TODAY]
        self.assertFalse(any(t.code == '600363' for t in buys), '止损当日不得买回')

    def test_kept_r7_zone_no_topup(self):
        """S8: 到期 & 在 top10 但浮亏 -7%（R7 观察窗，未到 14:30）→ 保留但不加仓"""
        positions = [
            pos('300937', 2500, 24.25, LAST_RE),
        ]
        acct = make_acct(positions=positions)
        self._prices['300937'] = 22.55              # 22.55/24.25-1 = -7.0%（R7 观察窗）
        acct, _ = self.run_re(acct, cash=900_000.0)
        # 未卖（无开盘破位、未到 14:30）
        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        self.assertEqual(sells, [])
        # 保留原仓、不加仓
        p = acct.get_position('300937')
        self.assertEqual(p.shares, 2500)
        buys = [t for t in acct.trades if t.action == '买入' and t.date == TODAY]
        self.assertFalse(any(t.code == '300937' for t in buys), 'R7 观察窗不得加仓')


class TestGlobalCooldown(Base):
    """S4/S6: 全局冷却——跨账户记录拦补差；memory 记录条件腿全过可买回并删除"""

    def test_cross_account_cooldown_blocks_topup(self):
        positions = [
            pos('600363', 6700, 16.32, LAST_RE),     # 到期 & 在 top10（fusion_dual 9/1 实盘持仓同构）
        ]
        acct = make_acct(aid='fusion_dual', positions=positions)
        TARGETS_HAS_600363 = TARGETS + [('600363', 120.0)]
        S.get_signal_targets = lambda *a, **k: TARGETS_HAS_600363
        try:
            state = make_state()
            # main 8/31 止损 600363 16.37，冷却中（全局记录）
            cooldown.add_stop_memory(state, '600363', 'main', 16.37, 10.5, '20260831')
            acct.cash = 900_000.0
            tushare = FakeTushare(trade_days_after_last_re(), latest_daily='20260901', closes=self._prices)
            store = FakeStore(acct)
            S.run_day(store, state, tushare, '20260901', TODAY, acct.id, set(), 0.0)
        finally:
            S.get_signal_targets = lambda *a, **k: TARGETS

        # 600363 保留（没被卖——它在 top10 且未触发风控）但不加仓（全局冷却拦补差）
        p = acct.get_position('600363')
        self.assertIsNotNone(p)
        self.assertEqual(p.shares, 6700)
        buys = [t for t in acct.trades if t.action == '买入' and t.date == TODAY]
        self.assertFalse(any(t.code == '600363' for t in buys), '跨账户冷却中不得加仓 600363')
        # main 记录仍在
        row = state.execute("SELECT status FROM trade_cooldown WHERE code='600363' AND strategy='main'").fetchone()
        self.assertEqual(row[0], 'cooldown')

    def test_memory_legs_pass_rebuy_deletes_record(self):
        """自家 memory 记录（时间腿已过），价格/模型腿全过 → 允许买回并删除"""
        state = make_state()
        cooldown.add_stop_memory(state, '301166', 'cmmr_fusion', 20.0, 100.0, '20260801')
        state.execute("UPDATE trade_cooldown SET status='memory' WHERE code='301166'")
        state.commit()
        # 301166 不在持仓（缺失目标）；现价 29.36 ≥ 20.0 ✓；score 123.1 ≥ 100 ✓
        acct = make_acct(positions=[])
        acct.cash = 1_300_000.0
        tushare = FakeTushare(trade_days_after_last_re(), latest_daily='20260901', closes=self._prices)
        store = FakeStore(acct)
        S.run_day(store, state, tushare, '20260901', TODAY, acct.id, set(), 0.0)
        p = acct.get_position('301166')
        self.assertIsNotNone(p, '条件腿全过应允许买回')
        row = state.execute("SELECT 1 FROM trade_cooldown WHERE code='301166' AND strategy='cmmr_fusion'").fetchone()
        self.assertIsNone(row, '买回后应删除本账户记忆')


class TestOtherGuards(Base):
    def test_t1_position_not_sold_even_in_risk(self):
        """S7: 今日买入（T+1）即使暴跌也不得当日卖"""
        positions = [pos('002879', 8000, 15.0, TODAY)]
        acct = make_acct(positions=positions)
        self._prices['002879'] = 13.0               # -13%（硬止损区，但 T+1）
        acct, _ = self.run_re(acct, cash=500_000.0)
        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        self.assertEqual(sells, [])
        self.assertIsNotNone(acct.get_position('002879'))

    def test_crash_day_reeval_sells_but_no_buy_no_advance(self):
        """S9: 大跌市重评日——到期非目标照卖、在 top10 保留；停买；last_re 不推进"""
        positions = [
            pos('002879', 8000, 16.61, LAST_RE),     # 到期 & 不在 top10
            pos('003001', 3800, 15.81, LAST_RE),     # 到期 & 在 top10
        ]
        acct = make_acct(positions=positions)
        acct.cash = 900_000.0
        state = make_state()
        tushare = FakeTushare(trade_days_after_last_re(), latest_daily='20260901', closes=self._prices)
        store = FakeStore(acct)
        S.is_crash_market = lambda *a, **k: (True, '测试大跌市')
        try:
            S.run_day(store, state, tushare, '20260901', TODAY, acct.id, set(), 0.0)
        finally:
            S.is_crash_market = lambda *a, **k: (False, '')
        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        buys = [t for t in acct.trades if t.action == '买入' and t.date == TODAY]
        self.assertEqual({t.code for t in sells}, {'002879'})
        self.assertEqual(buys, [], '大跌市停买')
        self.assertIsNotNone(acct.get_position('003001'), 'top10 内保留')
        self.assertNotEqual(acct.config.get('last_rebalance_date'), TODAY, '大跌市不推进重评日')

    def test_non_reeval_day_old_mode_all_topup(self):
        """S10a: 非重评日 + 显式 topup='all'（旧口径/回滚路径）——用全部现金等分买缺失目标"""
        S.ACCOUNTS['cmmr_fusion']['topup'] = 'all'
        try:
            self._s10a_body()
        finally:
            S.ACCOUNTS['cmmr_fusion']['topup'] = 'gap'

    def _s10a_body(self):
        positions = [
            pos('003001', 5000, 16.0, '20260901'),   # 今天之前 top-up 的仓
            pos('002879', 8000, 16.61, '20260901'),
        ]
        # 上次重评日是今天 → 非重评日
        acct = make_acct(positions=positions, cfg={'last_rebalance_date': TODAY})
        acct, _ = self.run_re(acct, cash=120_000.0, trade_date='20260903')
        buys = [t for t in acct.trades if t.action == '买入' and t.date == '20260903']
        # 只买缺失目标（003001 已持有 → 不买）；002879 不在目标 → 不买也不卖
        self.assertFalse(any(t.code in ('003001', '002879') for t in buys))
        self.assertTrue(len(buys) > 0, '有现金应补缺失目标')
        self.assertTrue(all(t.reason == '信号top10买入' for t in buys))
        self.assertIsNotNone(acct.get_position('002879'))
        # last_re 不推进（非重评日）
        self.assertEqual(acct.config.get('last_rebalance_date'), TODAY)


class TestTopupGapMode(Base):
    """S10b/S11/S12: 2026-09-11 碎仓修复——topup='gap' 每日只补已持有目标仓 + 重评日碎仓清理"""

    def test_gap_mode_no_new_codes_only_fill_held_targets(self):
        """S10b: 未持有的目标票一律不买（现金留存），只把已持有的目标仓补到等权"""
        S.ACCOUNTS['cmmr_fusion']['topup'] = 'gap'
        positions = [
            pos('003001', 100, 16.0, '20260901'),    # 目标 & 已持有，缺口远大于防碎门槛 → 补
            pos('002879', 8000, 16.61, '20260901'),  # 非目标仓 → 不动
        ]
        acct = make_acct(positions=positions, cfg={'last_rebalance_date': TODAY})
        # 每账户目标 8 只（TARGETS），现金 10 万 → per_target≈(100000+1628)/8≈12704
        # ⚠️ 2026-09-21 防碎门槛：缺口须 > NAV×2.5%（本例 NAV≈24.1万 → 门槛≈6026），
        #    故此处 003001 持仓取 100 股（缺口≈1.1万）；门槛拦截场景见 S10c。
        acct, _ = self.run_re(acct, cash=100_000.0, trade_date='20260903')
        buys = [t for t in acct.trades if t.action == '买入' and t.date == '20260903']
        self.assertTrue(buys, '已持有目标仓低于等权应补缺口')
        self.assertTrue(all(t.code == '003001' for t in buys), f'只能补已持有目标仓，实际 {[t.code for t in buys]}')
        self.assertTrue(all(t.reason == '窗口内补缺口' for t in buys))
        # 未持有的目标票（300753 等）一只都不能买
        self.assertFalse(any(t.code in TARGET_CODES - {'003001'} for t in buys))
        # 现金留存（没有买满 → 剩余现金 > 0）
        self.assertGreater(acct.cash, 0)
        self.assertIsNotNone(acct.get_position('002879'))
        self.assertEqual(acct.config.get('last_rebalance_date'), TODAY, '非重评日不推进 last_re')

    def test_gap_mode_min_position_gate(self):
        """S10c: 防碎门槛（2026-09-21 用户拍板）—— 缺口 < NAV×2.5% 时不补、留现金。

        原门槛是固定 2000 元（= 0.18% NAV，等于不设防，会补出 <1% 碎仓）。
        本例 003001 缺口仅 ≈5.4 千，而 NAV≈24.1万×2.5%≈6.0千 → 应当**一只都不补**。"""
        S.ACCOUNTS['cmmr_fusion']['topup'] = 'gap'
        positions = [
            pos('003001', 500, 16.0, '20260901'),    # 缺口 ≈5.4 千 < 门槛 ≈6.0 千 → 不补
            pos('002879', 8000, 16.61, '20260901'),  # 非目标仓 → 不动
        ]
        acct = make_acct(positions=positions, cfg={'last_rebalance_date': TODAY})
        cash_before = 100_000.0
        acct, _ = self.run_re(acct, cash=cash_before, trade_date='20260903')
        buys = [t for t in acct.trades if t.action == '买入' and t.date == '20260903']
        self.assertEqual(buys, [], f'缺口低于 NAV×2.5% 门槛不应补仓（防碎），实际 {[t.code for t in buys]}')
        self.assertEqual(acct.cash, cash_before, '不应动用现金')


    def test_reeval_dust_cleanup(self):
        """S11: 重评日碎仓清理——窗口内 top-up 的 <1% 残仓卖出（reason=碎仓清理）；
        权重正常（≥1%）的窗口内仓仍按 9/2 语义保留"""
        positions = [
            pos('300364', 200, 27.0, '20260901'),     # 窗口内 + 权重≈0.55% <1% 且不在 top10 → 清理
            pos('688191', 3000, 19.0, '20260901'),    # 窗口内 + 权重≈6% 且不在 top10 → 保留（信号未到期）
            pos('003001', 3800, 15.81, LAST_RE),      # 满窗口 & 在 top10 → 保留 + 补差
        ]
        acct = make_acct(positions=positions, cfg={'last_rebalance_date': LAST_RE})
        acct, _ = self.run_re(acct, cash=1_000_000.0, trade_date=TODAY)   # NAV≈113万 → 300364 权重 0.49%
        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        dust = [t for t in sells if t.reason == '碎仓清理']
        self.assertEqual([t.code for t in dust], ['300364'], f'碎仓清理应只卖 300364，实际 {[t.reason for t in sells]}')
        self.assertIsNone(acct.get_position('300364'), '碎仓应已清掉')
        self.assertIsNotNone(acct.get_position('688191'), '≥1% 的窗口内仓不该被当碎仓清掉')

    def test_accounts_all_use_gap_mode(self):
        """S12: 生产账户全部 topup='gap'（单一来源校验，防回退到碎仓口径）"""
        for aid, cfg in S.ACCOUNTS.items():
            if cfg.get('manual'):
                continue
            self.assertEqual(cfg.get('topup', 'gap'), 'gap', f'{aid} 未使用 gap 口径')


class TestTpReentryBan(Base):
    """S11/S12: 2026-09-02 用户拍板——触发止盈(R6)的票不管是否在 top10 名单上，
    一律卖出且当日(TP_REENTRY_BAN_DAYS 内)禁买回；次日若仍在 top10 由买入逻辑重新接回。
    （止损类已有冷却：到重评日/10信号日，比止盈禁买更严，不受本机制影响）"""

    def _acct(self, last_re):
        positions = [
            # 在 top10：cost 10 → peak 11.5(+15%) → 现价 10.3（≤0.92×11.5=10.58，R6 区）
            Position(code='003001', name='中岩大地', shares=3800, avg_cost=10.0,
                     buy_date='20260818', peak_price=11.5),
            # 不在 top10：同样 R6 区
            Position(code='300364', name='中文在线', shares=4000, avg_cost=10.0,
                     buy_date='20260818', peak_price=11.5),
        ]
        acct = make_acct(positions=positions, cfg={'last_rebalance_date': last_re})
        return acct

    def test_normal_day_tp_sells_even_in_target_and_no_same_day_rebuy(self):
        """S11: 非重评日——在 top10 的票 R6 照卖（安全规则不因名单豁免），且当日禁买回"""
        acct = self._acct(last_re=TODAY)
        self._prices['003001'] = 10.3
        self._prices['300364'] = 10.3
        acct, state = self.run_re(acct, cash=900_000.0, trade_date='20260903')
        sells = [t for t in acct.trades if t.action == '卖出' and t.date == '20260903']
        buys = [t for t in acct.trades if t.action == '买入' and t.date == '20260903']
        # 两只都触发 R6 卖出（在榜 003001 不豁免安全规则）
        self.assertEqual({t.code for t in sells}, {'003001', '300364'})
        self.assertTrue(all(t.reason == '回撤止盈' for t in sells))
        # 当日禁买回（现金充足也不许同日原价接回）
        self.assertFalse(any(t.code in ('003001', '300364') for t in buys),
                         f'止盈卖出当日不得买回: {[t.code for t in buys]}')
        self.assertIsNone(acct.get_position('003001'))
        self.assertIsNone(acct.get_position('300364'))
        # 禁买回记录落库（status 表 trade_tp_ban）
        for code in ('003001', '300364'):
            r = state.execute(
                "SELECT sell_date FROM trade_tp_ban WHERE code=? AND strategy='cmmr_fusion'",
                (code,)).fetchone()
            self.assertIsNotNone(r, f'{code} 应有止盈禁买记录')

    def test_next_day_still_top10_not_reentered_until_reeval(self):
        """S11b（2026-09-11 gap 口径改）：次日禁买期满且在 top10 → **窗口内不接回**
        （与止损票的冷却时间腿口径统一：卖出的票一律等下次重评日再按等权纳入）"""
        acct = self._acct(last_re=TODAY)
        self._prices['003001'] = 10.3
        self._prices['300364'] = 10.3
        state = make_state()
        acct, _ = self.run_re(acct, cash=900_000.0, trade_date='20260903', state=state)  # 卖出+禁买
        acct2, _ = self.run_re(acct, cash=None, trade_date='20260904', state=state)      # 次日同库
        buys_d2 = [t for t in acct2.trades if t.action == '买入' and t.date == '20260904']
        # gap 口径：窗口内不接回（即便禁买期已满、且 003001 仍在 top10）
        self.assertFalse(any(t.code == '003001' for t in buys_d2),
                         f'窗口内不得接回已卖出票（实际买入 {[t.code for t in buys_d2]}）')
        self.assertIsNone(acct2.get_position('003001'))
        self.assertIsNone(acct2.get_position('300364'))
        # 未买回 → 禁买记录都留着（下次重评日按等权重新纳入时才会清）
        for code in ('003001', '300364'):
            r = state.execute("SELECT 1 FROM trade_tp_ban WHERE code=? AND strategy='cmmr_fusion'",
                              (code,)).fetchone()
            self.assertIsNotNone(r, f'{code} 未接回 → 禁买记录应保留')

    def test_reeval_day_in_target_tp_sells_not_readded(self):
        """S12: 重评日——在 top10 的到期仓若处 R6 区 → 止盈卖出（不保留不补差），当日禁加回"""
        acct = self._acct(last_re=LAST_RE)
        self._prices['003001'] = 10.3
        self._prices['300364'] = 10.3
        acct, state = self.run_re(acct, cash=900_000.0, trade_date=TODAY)
        sells = [t for t in acct.trades if t.action == '卖出' and t.date == TODAY]
        buys = [t for t in acct.trades if t.action == '买入' and t.date == TODAY]
        # 003001 到期且在 top10 但处 R6 区 → 照样止盈卖出（名单不豁免安全规则）
        s = {t.code: t for t in sells}
        self.assertEqual(s.get('003001').reason if '003001' in s else None, '回撤止盈')
        # 当日不得补差/建回 003001；其余目标照常建仓
        self.assertFalse(any(t.code == '003001' for t in buys))
        self.assertIsNone(acct.get_position('003001'))
        others = {c for c, _ in TARGETS if c != '003001'}
        for code in others:
            self.assertIsNotNone(acct.get_position(code), f'{code} 应被建仓')
        # 重评日推进
        self.assertEqual(acct.config.get('last_rebalance_date'), TODAY)


class TestTpBanSignalMain(Base):
    """S13/S14: 主账户版止盈禁买（signal 日口径，达目标价/回撤止盈卖出后禁买回；
    count_signal_days_since：sell_date 之后信号日数，期满自动删记录）"""

    def test_same_day_blocked_expiry_cleanup(self):
        state = make_state()   # signal_history 已有 20260901/20260902
        # 卖出日 20260901：之后信号日 1 个（0902）→ ban_days=1 期满 → 放行并删记录
        cooldown.add_tp_ban(state, '003001', 'main', '20260901')
        blk, why = cooldown.check_tp_ban_signal(state, '003001', 'main', 1)
        self.assertFalse(blk, why)
        r = state.execute("SELECT 1 FROM trade_tp_ban WHERE code='003001' AND strategy='main'").fetchone()
        self.assertIsNone(r, '期满应自动删记录')
        # 当天卖出（20260902，之后 0 信号日）→ ban_days=1 仍拦（当日禁买回）
        cooldown.add_tp_ban(state, '003001', 'main', '20260902')
        blk, why = cooldown.check_tp_ban_signal(state, '003001', 'main', 1)
        self.assertTrue(blk, '当日应禁买回')
        self.assertIn('止盈禁买期', why)
        # ban_days=3（将来"禁几天"调大）→ elapsed=1 <3 仍拦
        cooldown.add_tp_ban(state, '003001', 'main', '20260901')
        blk, _ = cooldown.check_tp_ban_signal(state, '003001', 'main', 3)
        self.assertTrue(blk)
        # 无记录放行
        self.assertEqual(cooldown.check_tp_ban_signal(state, '999999', 'main', 1), (False, ''))

    def test_single_source_constant(self):
        """S14: TP_REENTRY_BAN_DAYS 单一来源 cooldown.py（策略账户/主账户共用同一旋钮）"""
        self.assertEqual(S.TP_REENTRY_BAN_DAYS, cooldown.TP_REENTRY_BAN_DAYS)


if __name__ == '__main__':
    unittest.main(verbosity=2)
