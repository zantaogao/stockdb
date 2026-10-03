"""
统一交易引擎 v1 — 单引擎多账户，共享信号源
=========================================
设计原则:
  - 单引擎管理所有账户（main/short/sim）
  - 每天只运行一次combined_score.py，所有账户共享信号
  - 每账户独立状态文件，互不影响
  - 完整绩效追踪（收益曲线、夏普、回撤、胜率）
  - 兼容旧版sim_engine接口（SimEngine/SimAccount）

用法：
    from core.sim_engine import TradeEngine
    engine = TradeEngine()
    result = engine.run_daily(dry_run=True)

兼容旧接口:
    from core.sim_engine import SimEngine
    engine = SimEngine()
    engine.run_daily()
"""
import json, os, sys, time, math, re
import numpy as np
from datetime import datetime, date
from pathlib import Path
from collections import OrderedDict
from threading import Lock

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.unified_account import AccountStore, Account, Trade
from core.signal_fetcher import SignalFetcher
from core.execution import ExecutionEngine, OrderManager

# ── 引擎锁（防止并发重复运行）────────────────────────────────────
_engine_lock = Lock()

# ── 旧版SimEngine兼容 ─────────────────────────────────────
DEFAULT_CONFIG = {
    "initial_capital": 1_000_000.0,
    "max_positions": 5,
    "min_cash_reserve": 10_000.0,
    "buy_score_threshold": 5.0,
    "buy_score_col": "reg20",
    "buy_max_upside_deviation": 25,
    "position_sizing": {
        "score_high": {"min": 12.0, "pct": 0.25},
        "score_mid": {"min": 8.0, "pct": 0.15},
        "score_low": {"min": 5.0, "pct": 0.10},
    },
    "stop_loss_hard": -12.0,
    "stop_loss_trailing": 8.0,
    "take_profit": 25.0,
    "signal_sell_threshold": -2.0,
    "market_risk_enabled": True,
    "max_same_industry": 2,
    "annual_trading_days": 242,
}


class SimAccount:
    """旧版SimAccount兼容 — 从统一账户模型适配（deprecated: 使用 core.unified_account.Account）"""

    def __init__(self, account: Account = None, config: dict = None):
        import warnings
        warnings.warn("SimAccount is deprecated — use core.unified_account.Account",
                      DeprecationWarning, stacklevel=2)
        if account:
            self._acct = account
        else:
            self._acct = Account("sim", "新引擎", 1000000.0, config or DEFAULT_CONFIG)

    @property
    def cash(self):
        return self._acct.cash

    @cash.setter
    def cash(self, v):
        self._acct.cash = v

    @property
    def positions(self):
        return self._acct.positions

    @property
    def trades(self):
        return self._acct.trades

    @property
    def nav_history(self):
        return self._acct.nav_history

    @property
    def config(self):
        return self._acct.config

    def get_position(self, code):
        return self._acct.get_position(code)

    def position_count(self):
        return self._acct.position_count

    def get_position_value(self, price_map):
        val = 0
        for p in self._acct.positions:
            cp = price_map.get(p.code)
            if cp:
                val += cp * p.shares
        return val

    def total_nav(self, price_map=None):
        val = self.get_position_value(price_map if price_map else {})
        return self.cash + val

    def buy(self, code, name, price, shares, reason=""):
        cost = price * shares
        if cost > self.cash:
            return False, "现金不足: 需%.0f, 有%.0f" % (cost, self.cash)
        from core.unified_account import Position
        pos = Position(code=code, name=name, shares=shares, avg_cost=price,
                       buy_date=datetime.now().strftime("%Y-%m-%d"),
                       peak_price=price)
        self._acct.add_position(pos)
        self._acct.trades.append(Trade(
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            action="买入", code=code, name=name,
            price=price, shares=shares, amount=cost,
            reason=reason or "信号买入",
        ))
        self._acct.cash -= cost
        return True, "买入 %s %d股 @ %.2f" % (code, shares, price)

    def sell(self, code, price, shares=None, reason="卖出"):
        pos = self._acct.get_position(code)
        if not pos:
            return False, "未持有 %s" % code
        sell_shares = shares if shares and shares <= pos.shares else pos.shares
        if sell_shares <= 0:
            return False, "无股可卖"
        pnl_pct = round((price / pos.avg_cost - 1) * 100, 2)
        amount = price * sell_shares
        self._acct.cash += amount
        pos.shares -= sell_shares
        self._acct.trades.append(Trade(
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            action="卖出", code=code, name=pos.name,
            price=price, shares=sell_shares, amount=amount,
            pnl_pct=pnl_pct, reason=reason,
        ))
        if pos.shares <= 0:
            self._acct.remove_position(code)
        return True, "卖出 %s %d股 @ %.2f, PnL %.2f%%" % (code, sell_shares, price, pnl_pct)

    def record_nav(self, price_map):
        return self._acct.record_nav(price_map)

    def to_dict(self):
        return self._acct.to_dict()

    @classmethod
    def from_dict(cls, d):
        acct = Account.from_dict(d)
        return cls(account=acct)

    def _notify(self, action, code, name, price, shares, reason='', pnl=None):
        try:
            p = BASE / 'pending_alerts.json'
            entry = {
                'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'time': datetime.now().strftime('%m-%d %H:%M'),
                'action': action, 'code': code, 'name': name,
                'price': round(price, 2), 'shares': shares,
                'reason': reason,
            }
            if pnl is not None:
                entry['pnl'] = round(pnl, 2)
            alerts = []
            if p.exists():
                try:
                    alerts = json.loads(p.read_text())
                except:
                    pass
            alerts.append(entry)
            if len(alerts) > 10:
                alerts = alerts[-10:]
            p.write_text(json.dumps(alerts, ensure_ascii=False, indent=2))
        except:
            pass


class SimEngine:
    """旧版SimEngine兼容 — 操作sim_state.json（deprecated: 使用 core.sim_engine.TradeEngine）"""

    def __init__(self, state_path=None, config=None):
        import warnings
        warnings.warn("SimEngine is deprecated — use core.sim_engine.TradeEngine",
                      DeprecationWarning, stacklevel=2)
        self.state_path = Path(state_path) if state_path else BASE / 'sim_state.json'
        self.config = config or DEFAULT_CONFIG.copy()
        self.acct = None
        self._load()

    def _load(self):
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding='utf-8'))
                self.acct = SimAccount.from_dict(data)
                file_cfg = data.get('config', {})
                self.config = {**DEFAULT_CONFIG, **file_cfg}
                return True
            except Exception as e:
                print("  ⚠️ 状态文件读取失败: %s，新建账户" % e)
        self.acct = SimAccount(config=self.config)
        return False

    def save(self):
        data = self.acct.to_dict()
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
        )

    def _get_signals(self, ref_date=None):
        """兼容旧版: 解析combined_score.py文本输出"""
        cmd = [sys.executable, str(BASE / 'scripts' / 'combined_score.py')]
        if ref_date:
            cmd += ['--date', ref_date]
        import subprocess
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        signals = []
        for line in r.stdout.split('\n'):
            parts = line.strip().split()
            if len(parts) >= 7 and parts[0].isdigit():
                try:
                    pct_indices = [j for j, p in enumerate(parts) if '%' in p]
                    if len(pct_indices) < 2:
                        continue
                    reg20_pos = pct_indices[0]
                    dev_pos = pct_indices[1]
                    code = parts[1]
                    name = parts[2]
                    fusion = float(parts[3])
                    reg20 = float(parts[reg20_pos].replace('%', ''))
                    dev120 = float(parts[dev_pos].replace('%', ''))
                    signals.append({
                        'code': code, 'name': name,
                        'fusion': fusion, 'reg20': reg20,
                        'reg40': 0, 'reg10': 0, 'dev120': dev120,
                    })
                except:
                    continue
        return signals

    def _fetch_prices(self, codes):
        """兼容旧版价格获取"""
        return ExecutionEngine().fetch_prices(codes)

    def _market_risk(self):
        return ExecutionEngine().market_risk_score().get('score', 1.0)

    def _check_sells(self, signals_map, price_map):
        return OrderManager().check_sells(self.acct, signals_map, price_map)

    def _check_buys(self, signals, signals_map, held_codes, price_map):
        """兼容旧版买入检查"""
        slots = self.config['max_positions'] - len(self.acct.positions)
        if slots <= 0 or self.acct.cash < self.config['min_cash_reserve']:
            return []

        use_col = self.config['buy_score_col']
        buy_orders = []
        skipped_dev = []

        for s in signals:
            code = s['code']
            if code in held_codes:
                continue
            score = s.get(use_col, s['fusion'])
            if score < self.config['buy_score_threshold']:
                continue
            dev = s.get('dev120', 0)
            if dev > self.config['buy_max_upside_deviation']:
                skipped_dev.append("%s(年线%.0f%%)" % (s['name'], dev))
                continue
            price = price_map.get(code, 0)
            if price <= 0:
                continue

            pct = self.config['position_sizing']['score_low']['pct']
            if score >= self.config['position_sizing']['score_high']['min']:
                pct = self.config['position_sizing']['score_high']['pct']
            elif score >= self.config['position_sizing']['score_mid']['min']:
                pct = self.config['position_sizing']['score_mid']['pct']

            max_amt = self.acct.cash * pct
            shares = int(max_amt / price / 100) * 100
            if shares < 100:
                continue

            buy_orders.append({
                'code': code, 'name': s.get('name', ''),
                'price': price, 'shares': shares,
                'score': score, 'method': "%d%%仓位" % (pct * 100),
            })

        if skipped_dev:
            print("  ⚠️ 追高过滤: %s" % ', '.join(skipped_dev[:3]))
        buy_orders.sort(key=lambda x: x['score'], reverse=True)
        return buy_orders[:slots]

    def run_daily(self, ref_date=None, price_map=None, dry_run=False):
        """兼容旧版run_daily"""
        today = ref_date or datetime.now().strftime("%Y-%m-%d")
        print("\n" + "="*60)
        print("📊 模拟交易引擎 — %s" % today)
        print("="*60)
        print("  💰 现金: %0.f  持仓: %d只" % (self.acct.cash, len(self.acct.positions)))

        print("\n📡 获取评分...")
        signals = self._get_signals(ref_date)
        signals_map = {s['code']: s for s in signals}
        print("  ✅ %d 只有信号" % len(signals))

        all_codes = list(set(
            [s['code'] for s in signals] +
            [p.code for p in self.acct.positions]
        ))
        if not price_map:
            price_map = self._fetch_prices(all_codes)
            for s in signals:
                if s['code'] not in price_map and s.get('price'):
                    price_map[s['code'] if s['code'] else '_'] = s['price']
        self._latest_prices = price_map

        risk_coef = self._market_risk()
        risk_label = '牛市' if risk_coef >= 0.7 else ('震荡' if risk_coef >= 0.4 else '熊市')
        print("\n🌍 市场风险: %.2f (%s)  仓位系数 ×%.2f" % (risk_coef, risk_label, risk_coef))

        print("\n🔴 卖出检查...")
        sell_orders = self._check_sells(signals_map, price_map)
        for order in sell_orders:
            exec_price = ExecutionEngine().apply_slippage(order['price'], 'sell')
            ok, msg = self.acct.sell(order['code'], exec_price,
                                     order['shares'], order['reason'])
            ico = '✅' if ok else '❌'
            print("  %s %s %8s PnL %+.1f%%  %s" % (
                ico, order['code'], order['name'], order['pnl'], order['reason'][:40]))
        if not sell_orders:
            print("  无卖出操作")

        print("\n🟢 买入检查...")
        held_codes = {p.code for p in self.acct.positions}
        buy_orders = self._check_buys(signals, signals_map, held_codes, price_map)
        for order in buy_orders:
            cost = order['price'] * order['shares']
            if cost > self.acct.cash:
                order['shares'] = int(self.acct.cash * 0.95 / order['price'] / 100) * 100
                if order['shares'] < 100:
                    print("  ⏭ %s %8s 现金不足跳过" % (order['code'], order['name']))
                    continue
            reason = "信号%.0f/%s" % (order['score'], order['method'])
            ok, msg = self.acct.buy(order['code'], order['name'],
                                    order['price'], order['shares'], reason)
            ico = '✅' if ok else '❌'
            print("  %s %s %8s %s %d股 @ %.2f" % (
                ico, order['code'], order['name'], order['method'],
                order['shares'], order['price']))
        if not buy_orders:
            slots = self.config['max_positions'] - len(self.acct.positions)
            print("  无合格买入信号 (空位%d个)" % slots)

        nav_entry = self.acct.record_nav(price_map)
        print("\n  💰 NAV: %0.f  (%+.4f%%)" % (nav_entry['nav'], nav_entry['returns']))

        if not dry_run:
            self.save()
            print("\n✅ 状态已保存")

        return {
            'date': today,
            'nav': nav_entry,
            'buys': buy_orders,
            'sells': sell_orders,
            'risk': {'score': risk_coef, 'label': risk_label},
            'signals_count': len(signals),
        }

    def performance_summary(self):
        metrics = self.calc_metrics()
        if isinstance(metrics, dict) and "status" in metrics and "total_return" not in metrics:
            return metrics["status"]
        lines = []
        lines.append("=" * 50)
        lines.append("📊 模拟交易绩效报告")
        lines.append("=" * 50)
        for k, v in metrics.items():
            lines.append("  %12s: %s" % (k, v))
        lines.append("-" * 50)
        recent = [t for t in self.acct.trades if t.action == "卖出"][-10:]
        if recent:
            lines.append("\n📋 最近10笔平仓:")
            lines.append("  %12s %8s %8s %8s %20s" % ("日期", "代码", "名称", "盈亏", "原因"))
            lines.append("  " + "─" * 56)
            for t in reversed(recent):
                pnl = "%+.1f%%" % t.pnl_pct if t.pnl_pct is not None else "持仓中"
                reason = t.reason[:20] if t.reason else ''
                lines.append("  %12s %8s %8s %8s %20s" % (
                    t.date[:10], t.code, t.name, pnl, reason))
        if self.acct.positions:
            lines.append("\n📌 当前持仓:")
            for p in self.acct.positions:
                lines.append("  %s %8s %d股 @ %.2f  买入%s" % (
                    p.code, p.name, p.shares, p.avg_cost, p.buy_date))
        return '\n'.join(lines)

    def calc_metrics(self):
        nh = self.acct.nav_history
        if len(nh) < 2:
            return {"status": "数据不足，至少需要2个交易日"}
        initial = self.acct.initial_capital
        current_nav = _get_nav(nh[-1])
        total_return = (current_nav / initial - 1) * 100
        daily_rets = [h.get('returns', 0) for h in nh if h.get('returns') is not None]
        if len(daily_rets) < 2:
            return {"total_return": round(total_return, 2), "status": "日收益率数据不足"}
        daily_rets = np.array(daily_rets)
        avg_ret = np.mean(daily_rets)
        std_ret = np.std(daily_rets, ddof=1)
        n_days = len(nh)
        years = n_days / self.config['annual_trading_days']
        annual_ret = ((current_nav / initial) ** (1 / years) - 1) * 100 if years > 0 else 0
        rf_daily = 0.02 / self.config['annual_trading_days']
        excess_rets = daily_rets - rf_daily * 100
        sharpe = np.mean(excess_rets) / std_ret * math.sqrt(self.config['annual_trading_days']) if std_ret > 0 else 0
        nav_values = np.array([_get_nav(h) for h in nh])
        peak = np.maximum.accumulate(nav_values)
        dd = (nav_values - peak) / peak * 100
        max_drawdown = np.min(dd)
        max_dd_days = int(np.argmin(dd) - np.argmax(peak[:np.argmin(dd)+1])) if np.argmin(dd) > 0 else 0
        closed_trades = [t for t in self.acct.trades if t.action == "卖出" and t.pnl_pct is not None]
        wins = [t for t in closed_trades if t.pnl_pct > 0]
        loss = [t for t in closed_trades if t.pnl_pct <= 0]
        win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
        avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
        avg_loss = np.mean([t.pnl_pct for t in loss]) if loss else 0
        pf = abs(sum(t.pnl_pct for t in wins) / sum(t.pnl_pct for t in loss)) if loss and sum(t.pnl_pct for t in loss) < 0 else float('inf')
        # 持仓命中率：每只持仓比较 当前市值 vs 买入成本
        hold_hit = 0
        if hasattr(self, '_latest_prices'):
            for p in self.acct.positions:
                if p.code in self._latest_prices:
                    cur_price = self._latest_prices[p.code]
                    if cur_price > p.avg_cost:
                        hold_hit += 1
        hold_hit_rate = round(hold_hit / max(len(self.acct.positions), 1) * 100, 1)
        return OrderedDict([
            ("交易天数", n_days),
            ("总收益率", "%+.2f%%" % total_return),
            ("年化收益率", "%+.2f%%" % annual_ret),
            ("年化波动率", "%.2f%%" % (std_ret * math.sqrt(self.config['annual_trading_days']))),
            ("夏普比率", "%.2f" % sharpe),
            ("最大回撤", "%.2f%%" % max_drawdown),
            ("最大回撤持续", "%d天" % max_dd_days),
            ("累计交易", len(closed_trades)),
            ("胜率", "%.1f%%" % win_rate),
            ("平均盈利", "%+.2f%%" % avg_win if wins else "N/A"),
            ("平均亏损", "%+.2f%%" % avg_loss if loss else "N/A"),
            ("盈亏比", "%.2f" % pf if pf != float('inf') else "∞"),
            ("当前净值", "%0.f" % current_nav),
            ("当前现金", "%0.f" % self.acct.cash),
            ("持仓数量", len(self.acct.positions)),
            ("持仓命中率", "%s%%" % hold_hit_rate),
        ])


# ── 统一交易引擎（新）───────────────────────────────────────
class TradeEngine:
    """统一交易引擎 — 支持多账户，共享信号"""

    def __init__(self, account_ids: list = None):
        self.store = AccountStore()
        self.signals = SignalFetcher()
        self.exec_engine = ExecutionEngine()
        self.orders = OrderManager()
        from core.trade_log import TradeLog
        self.trade_log = TradeLog()
        # 加载账户
        if account_ids:
            self.accounts = {aid: self.store.load(aid) for aid in account_ids}
        else:
            self.accounts = self.store.get_all_accounts()

    def run_daily(self, ref_date: str = None, dry_run: bool = False) -> dict:
        """
        每日运行 — 所有账户共享信号
        """
        today = ref_date or datetime.now().strftime("%Y-%m-%d")
        # 引擎锁：防止并发重复运行
        if not _engine_lock.acquire(blocking=False):
            print("  ⚠️ 引擎已在运行中，跳过本次调用")
            return {'status': 'already_running'}
        try:
            return self._run_daily_inner(today, dry_run)
        finally:
            _engine_lock.release()

    def _run_daily_inner(self, today, dry_run) -> dict:
        print("\n" + "="*60)
        print("📊 统一交易引擎 — %s" % today)
        print("="*60)

        # 1. 获取信号（只运行一次）
        print("\n📡 获取信号...")
        signals = self.signals.fetch(ref_date=today)
        signals_map = {s['code']: s for s in signals}
        print("  ✅ %d 只信号股票" % len(signals))

        if not signals:
            print("  ⚠️ 无信号数据")
            # 保存所有账户NAV
            if not dry_run:
                for aid, acct in self.accounts.items():
                    self.store.save(acct)
            return {}

        # 2. 获取价格
        all_codes = set()
        for acct in self.accounts.values():
            all_codes.update(p.code for p in acct.positions)
        all_codes.update(s['code'] for s in signals)
        print("\n📡 获取价格...")
        price_map = self.exec_engine.fetch_prices(list(all_codes), today)
        print("  ✅ 获取到 %d 个价格" % len(price_map))

        # 3. 市场风险评估（全局）
        risk = self.exec_engine.market_risk_score()
        risk_coef = risk['score']
        risk_label = risk['label']
        print("\n🌍 市场风险: %.2f (%s)" % (risk_coef, risk_label))

        # 4. 每个账户独立运行
        results = {}
        for aid, acct in self.accounts.items():
            print("\n" + "─"*50)
            print("账户: %s (%s) | 现金%0.f | 持仓%d只" % (
                aid, acct.name, acct.cash, acct.position_count))
            result = self._run_account(acct, signals, signals_map, price_map, risk, dry_run, today)
            results[aid] = result
            if not dry_run:
                self.store.save(acct)

        return results

    def _run_account(self, account, signals, signals_map, price_map, risk, dry_run, today) -> dict:
        """运行单个账户的每日流程"""
        risk_coef = risk['score']

        # 卖出 — 应用滑点
        sell_orders = self.orders.check_sells(account, signals_map, price_map)
        sells_executed = []
        for order in sell_orders:
            pos = account.get_position(order['code'])
            if pos:
                exec_price = self.exec_engine.apply_slippage(order['price'], 'sell')
                pnl_pct = round((exec_price / pos.avg_cost - 1) * 100, 2)
                amount = exec_price * order['shares']
                account.cash += amount
                pos.shares -= order['shares']
                account.trades.append(Trade(
                    date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    action="卖出", code=order['code'], name=order['name'],
                    price=exec_price, shares=order['shares'],
                    amount=amount, pnl_pct=pnl_pct, reason=order['reason'],
                ))
                if pos.shares <= 0:
                    account.remove_position(order['code'])
                # 写入交易流水
                sig = signals_map.get(order['code'], {})
                self.trade_log.record_sell(
                    account.id, order['code'], order['name'],
                    order['shares'], exec_price, amount,
                    avg_cost=pos.avg_cost,
                    slippage=0.005, fee_rate=0.0003,
                    pnl=order['pnl'], pnl_pct=pnl_pct,
                    reason=order['reason'],
                    signal_score=sig.get('fusion', 0) or sig.get('reg20', 0),
                    hold_days=None, source='sim_engine'
                )
                sells_executed.append({
                    'code': order['code'], 'name': order['name'],
                    'shares': order['shares'], 'pnl': order['pnl'],
                    'reason': order['reason'], 'success': True,
                })
                print("  🔴 卖出 %s %8s %d股 @ %.2f(滑点后)  PnL %+.1f%%  %s" % (
                    order['code'], order['name'], order['shares'],
                    exec_price, order['pnl'], order['reason'][:30]))

        if not sell_orders:
            print("  无卖出操作")

        # 买入 — 应用滑点 + 市场风险系数
        held_codes = {p.code for p in account.positions}
        buy_orders = []
        for s in signals:
            code = s['code']
            if code in held_codes:
                continue
            order = self.orders.check_buy(account, s, price_map.get(code, 0), risk_coef)
            if not order:
                continue
            if len(account.positions) >= account.config.get('max_positions', 5):
                continue
            if account.cash < account.config.get('min_cash_reserve', 10000):
                continue
            # 买入滑点
            exec_price = self.exec_engine.apply_slippage(order['price'], 'buy')
            cost = exec_price * order['shares']
            if cost > account.cash:
                order['shares'] = int(account.cash * 0.95 / exec_price / 100) * 100
                if order['shares'] < 100:
                    continue
            reason = "信号%.0f/%s risk×%.2f" % (order['score'], order['method'], risk_coef)
            from core.unified_account import Position
            pos = Position(
                code=order['code'], name=order['name'],
                shares=order['shares'], avg_cost=exec_price,
                buy_date=datetime.now().strftime("%Y-%m-%d"),
                peak_price=exec_price,
            )
            account.add_position(pos)
            account.cash -= exec_price * order['shares']
            account.trades.append(Trade(
                date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                action="买入", code=order['code'], name=order['name'],
                price=exec_price, shares=order['shares'],
                amount=exec_price * order['shares'], reason=reason,
                signal_score=order.get('score'),
            ))
            buy_orders.append({
                'code': order['code'], 'name': order['name'],
                'shares': order['shares'], 'price': exec_price,
                'score': order['score'], 'success': True,
            })
            # 写入交易流水
            pct_str = order.get('method', '').replace('%仓位', '').replace(' ', '')
            try:
                position_pct = float(pct_str) / 100 if pct_str else 0.25
            except:
                position_pct = 0.25
            self.trade_log.record_buy(
                account.id, order['code'], order['name'],
                order['shares'], exec_price, exec_price * order['shares'],
                signal_score=order.get('score'), reason=reason,
                market_condition=risk.get('label', ''),
                risk_coef=risk_coef,
                position_pct=position_pct,
                source='sim_engine'
            )
            print("  🟢 买入 %s %8s %s %d股 @ %.2f(滑点后)" % (
                order['code'], order['name'], order['method'],
                order['shares'], exec_price))

        if not buy_orders:
            slots = account.config.get('max_positions', 5) - len(account.positions)
            print("  无买入操作 (空位%d个)" % slots)

        # 记录NAV
        nav_entry = account.record_nav(price_map)
        print("\n  💰 NAV: %0.f  (%+.4f%%)" % (nav_entry['nav'], nav_entry['returns']))

        if not dry_run:
            self.store.save(account)

        return {
            'nav': nav_entry,
            'buys': buy_orders,
            'sells': sells_executed,
            'risk': risk,
        }

    def performance_summary(self, account_id: str = None) -> str:
        """生成所有账户或指定账户的绩效报告"""
        if account_id:
            acct = self.store.load(account_id)
            engine = SimEngine(config=acct.config)
            engine.acct = SimAccount(acct)
            return engine.performance_summary()

        lines = []
        lines.append("=" * 60)
        lines.append("📊 所有账户绩效对比")
        lines.append("=" * 60)
        for aid in self.store.list_all():
            acct = self.store.load(aid)
            metrics = _calc_performance(acct)
            lines.append("\n--- %s (%s) ---" % (aid, acct.name))
            for k, v in metrics.items():
                lines.append("  %15s: %s" % (k, v))
        return '\n'.join(lines)


# ── 统一绩效计算 ────────────────────────────────────────────
def _get_nav(h):
    """兼容不同账户格式：nav / total_value"""
    if isinstance(h, dict):
        return h.get('nav') or h.get('total_value') or 0
    return 0

def _calc_performance(account: Account) -> OrderedDict:
    """统一绩效计算，适用于所有账户"""
    nh = account.nav_history
    if len(nh) < 2:
        return OrderedDict([("status", "数据不足，至少需要2个交易日")])

    initial = account.initial_capital
    current_nav = _get_nav(nh[-1])
    total_return = (current_nav / initial - 1) * 100
    daily_rets = [h.get('returns', 0) for h in nh if h.get('returns') is not None]
    if len(daily_rets) < 2:
        return OrderedDict([
            ("总收益率", "%+.2f%%" % total_return),
            ("状态", "日收益率数据不足"),
        ])
    daily_rets = np.array(daily_rets)
    std_ret = np.std(daily_rets, ddof=1)
    n_days = len(nh)
    years = n_days / 242
    annual_ret = ((current_nav / initial) ** (1 / years) - 1) * 100 if years > 0 else 0
    rf_daily = 0.02 / 242
    excess_rets = daily_rets - rf_daily * 100
    sharpe = np.mean(excess_rets / std_ret) * math.sqrt(242) if std_ret > 0 else 0
    nav_values = np.array([_get_nav(h) for h in nh])
    peak = np.maximum.accumulate(nav_values)
    dd = (nav_values - peak) / peak * 100
    max_drawdown = np.min(dd)
    max_dd_days = int(np.argmin(dd) - np.argmax(peak[:np.argmin(dd)+1])) if np.argmin(dd) > 0 else 0
    closed_trades = [t for t in account.trades if t.action == "卖出" and t.pnl_pct is not None]
    wins = [t for t in closed_trades if t.pnl_pct > 0]
    loss = [t for t in closed_trades if t.pnl_pct <= 0]
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.pnl_pct for t in loss]) if loss else 0
    pf = abs(sum(t.pnl_pct for t in wins) / sum(t.pnl_pct for t in loss)) if loss and sum(t.pnl_pct for t in loss) < 0 else float('inf')

    # 持仓命中率：每只持仓比较 当前价 vs 买入成本
    hold_hit = 0
    # 尝试从 latest_prices 获取实时价（如果从引擎调用）
    latest_prices = {}
    # 尝试从执行引擎缓存获取
    try:
        ee = ExecutionEngine()
        if hasattr(ee, '_latest_prices') and ee._latest_prices:
            latest_prices = ee._latest_prices
    except:
        pass

    # 如果没有实时价，用 nav_history 估算
    for p in account.positions:
        if p.code in latest_prices:
            cur_price = latest_prices[p.code]
        else:
            # 用最后两条NAV的pos_value变化估算
            cur_price = p.avg_cost  # fallback
        if cur_price > p.avg_cost:
            hold_hit += 1
    hold_hit_rate = round(hold_hit / max(len(account.positions), 1) * 100, 1)

    return OrderedDict([
        ("总收益率", "%+.2f%%" % total_return),
        ("年化收益率", "%+.2f%%" % annual_ret),
        ("年化波动率", "%.2f%%" % (std_ret * math.sqrt(242))),
        ("夏普比率", "%.2f" % sharpe),
        ("最大回撤", "%.2f%%" % max_drawdown),
        ("最大回撤持续", "%d天" % max_dd_days),
        ("交易天数", n_days),
        ("累计交易", len(closed_trades)),
        ("胜率", "%.1f%%" % win_rate),
        ("平均盈利", "%+.2f%%" % avg_win if wins else "N/A"),
        ("平均亏损", "%+.2f%%" % avg_loss if loss else "N/A"),
        ("盈亏比", "%.2f" % pf if pf != float('inf') else "∞"),
        ("当前净值", "%0.f" % current_nav),
        ("持仓数量", len(account.positions)),
        ("持仓命中率", "%s%%" % hold_hit_rate),
    ])


def cross_account_report() -> str:
    """生成所有账户的对比报告"""
    store = AccountStore()
    accts = store.get_all_accounts()
    if not accts:
        return "无账户数据"

    lines = []
    lines.append("=" * 70)
    lines.append("📊 跨账户绩效对比报告")
    lines.append("=" * 70)
    lines.append("%-10s %10s %8s %10s %8s %8s" % (
        "账户", "收益率", "夏普", "回撤", "胜率", "命中率"))
    lines.append("─" * 70)

    for aid, acct in accts.items():
        metrics = _calc_performance(acct)
        ret = metrics.get("总收益率", "?")
        sr = metrics.get("夏普比率", "?")
        dd = metrics.get("最大回撤", "?")
        wr = metrics.get("胜率", "?")
        hh = metrics.get("持仓命中率", "?")
        lines.append("%-10s %10s %8s %10s %8s %8s" % (
            aid, ret, sr, dd, wr, hh))

    lines.append("=" * 70)
    return '\n'.join(lines)


# ── 数据健康检查 ────────────────────────────────────────────
def check_all() -> dict:
    """数据完整性检查"""
    results = {}

    # 1. tushare.db (主力库)
    db_path = BASE / 'tushare.db'
    if db_path.exists():
        try:
            import duckdb
            conn = duckdb.connect(str(db_path), read_only=True)
            table_names = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
            conn.close()
            required = ['daily', 'index_daily', 'stock_info', 'signal_history']
            missing = [t for t in required if t not in table_names]
            if missing:
                results["tushare.db"] = {"ok": False, "message": "缺失表：%s" % missing}
            else:
                results["tushare.db"] = {"ok": True, "message": "%d 个表 OK" % len(table_names)}
        except Exception as e:
            results["tushare.db"] = {"ok": False, "message": str(e)}
    else:
        results["tushare.db"] = {"ok": False, "message": "文件不存在"}

    # 2. stock.db (已废弃，仅做兼容性检查)
    old_db_path = BASE / 'stock.db'
    if old_db_path.exists():
        results["stock.db (deprecated)"] = {
            "ok": True, 
            "message": f"文件存在 ({old_db_path.stat().st_size // 1024} KB)，但已废弃"
        }
    else:
        results["stock.db (deprecated)"] = {"ok": None, "message": "未找到，可清理"}

    # 3. 模型文件
    model_dir = BASE / 'models'
    required_models = ['lgb_reg_20d_v2.txt', 'lgb_reg_40d_v7.txt']  # 修(0927): 随0926重训换代(mac_v1/new_stkfactor已退役retired_)
    missing_models = []
    for m in required_models:
        if not (model_dir / m).exists():
            missing_models.append(m)
    if missing_models:
        results["模型文件"] = {"ok": False, "message": "缺失: %s" % missing_models}
    else:
        results["模型文件"] = {"ok": True, "message": "全部存在"}

    # 3. 标准化文件
    norm_files = ['norm_stats_v8.json', 'v10_v8_stats.json', 'v40_v8_stats.json']  # 0927审计：原3个文件名从未存在，死引用误报缺失
    missing_norm = []
    for f in norm_files:
        if not (model_dir / f).exists():
            missing_norm.append(f)
    if missing_norm:
        results["标准化文件"] = {"ok": False, "message": "缺失: %s" % missing_norm}
    else:
        results["标准化文件"] = {"ok": True, "message": "全部存在"}

    # 4. GTJA信号
    gtja_path = BASE / 'gtja_signal.json'
    if gtja_path.exists():
        try:
            data = json.loads(gtja_path.read_text())
            count = len(data.get('scores', {}))
            results["GTJA信号"] = {"ok": True, "message": "%d 只股票" % count}
        except:
            results["GTJA信号"] = {"ok": False, "message": "JSON解析失败"}
    else:
        results["GTJA信号"] = {"ok": False, "message": "文件不存在（可接受，不影响基本功能）"}

    # 5. 账户状态
    store = AccountStore()
    accts = store.list_all()
    if accts:
        results["账户状态"] = {"ok": True, "message": "已迁移 %d 个账户: %s" % (
            len(accts), ', '.join(accts))}
    else:
        results["账户状态"] = {"ok": False, "message": "无账户数据，请运行迁移"}

    return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='交易日期')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--account', help='指定账户，默认全部')
    parser.add_argument('--metrics', action='store_true', help='显示绩效')
    parser.add_argument('--report', action='store_true', help='跨账户对比报告')
    parser.add_argument('--health', action='store_true', help='数据健康检查')
    parser.add_argument('--compat', action='store_true', help='兼容模式（旧版SimEngine）')
    args = parser.parse_args()

    if args.health:
        results = check_all()
        for k, v in results.items():
            status = '✅' if v['ok'] else '❌'
            print("%s %s: %s" % (status, k, v['message']))
        sys.exit(0)

    if args.report:
        engine = TradeEngine()
        print(cross_account_report())
        sys.exit(0)

    if args.compat:
        engine = SimEngine()
        engine.run_daily(ref_date=args.date, dry_run=args.dry_run)
        if args.metrics:
            print("\n" + engine.performance_summary())
        sys.exit(0)

    engine = TradeEngine()
    result = engine.run_daily(ref_date=args.date, dry_run=args.dry_run)
    if args.account and result:
        if args.account in result:
            r = result[args.account]
            nav = r.get('nav', {})
            print("\n=== %s ===" % args.account)
            print("  NAV: %0.f (%+.2f%%)" % (nav.get('nav', 0), nav.get('returns', 0)))
            for b in r.get('buys', []):
                print("  BUY: %s %s %d@%.2f" % (b['code'], b['name'], b['shares'], b['price']))
            for s in r.get('sells', []):
                print("  SELL: %s %s %+.1f%%" % (s['code'], s['name'], s['pnl']))
    elif not args.account and result:
        for aid, r in result.items():
            nav = r.get('nav', {})
            print("\n=== %s ===" % aid)
            print("  NAV: %0.f (%+.2f%%)" % (nav.get('nav', 0), nav.get('returns', 0)))
            for b in r.get('buys', []):
                print("  BUY: %s %s %d@%.2f" % (b['code'], b['name'], b['shares'], b['price']))
            for s in r.get('sells', []):
                print("  SELL: %s %s %+.1f%%" % (s['code'], s['name'], s['pnl']))

    if args.metrics:
        print("\n" + engine.performance_summary())
