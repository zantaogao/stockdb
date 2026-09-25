"""
执行引擎 v1
===================
接收风控信号（买入/加仓/减仓/清仓），按规则下单，更新持仓/现金/NAV，记录流水。

流程：
1. 获取实时价格（TDX/Sina 并发 → DB 兜底）
2. 按信号类型执行：
   - 买入：检查仓位上限、现金，计算买入数量
   - 加仓：在现有持仓基础上追加
   - 减仓：卖出指定比例或全部
   - 清仓：全部卖出
3. 更新账户状态（持仓、现金、NAV）
4. 写入交易流水

用法：
    from core.executor import Executor
    ex = Executor()
    result = ex.execute_signal('main', signal_dict)
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.unified_account import AccountStore, Position
from core.trade_log import TradeLog
from core.prices import fetch_close_from_db, fetch_prices_batch
from core.db import get_db


class Executor:
    """执行引擎"""

    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir) if base_dir else Path.home() / '.hermes' / 'stockdb'
        self.store = AccountStore()
        self.trade_log = TradeLog()
        self._price_cache = {}

    def _get_price(self, code):
        """统一价格获取：先缓存，实时价→DB兜底，带15秒TTL"""
        import time
        now = time.time()
        if code in self._price_cache:
            entry = self._price_cache[code]
            if now - entry['ts'] < 15:
                return entry['price']

        from core.prices import fetch_prices_batch
        prices = fetch_prices_batch([code])
        if code in prices and prices[code] and float(prices[code]) > 0:
            price = float(prices[code])
        else:
            from core.prices import fetch_close_from_db
            _, price = fetch_close_from_db(code)
            price = float(price) if price else 0

        if price > 0:
            self._price_cache[code] = {'price': price, 'ts': now}
        return price

    def _batch_get_prices(self, codes: list) -> dict:
        """批量预取价格，缓存所有结果"""
        import time
        now = time.time()
        need = []
        result = {}
        for c in codes:
            if c in self._price_cache:
                entry = self._price_cache[c]
                if now - entry['ts'] < 15:
                    result[c] = entry['price']
                    continue
            need.append(c)

        if need:
            from core.prices import fetch_prices_batch, fetch_close_from_db
            prices = fetch_prices_batch(need)
            for c in need:
                if c in prices and prices[c] and float(prices[c]) > 0:
                    price = float(prices[c])
                else:
                    _, price = fetch_close_from_db(c)
                    price = float(price) if price else 0
                if price > 0:
                    self._price_cache[c] = {'price': price, 'ts': now}
                    result[c] = price
        return result

    def execute_signal(self, account_id: str, signal: dict, dry_run: bool = False) -> dict:
        """
        执行一个信号。

        Args:
            account_id: 账户ID
            signal: 信号字典，格式如：
                {
                    'type': 'BUY'/'ADD'/'REDUCE'/'CLEAR',
                    'code': '600519',
                    'name': '贵州茅台',
                    'score': 85.0,
                    'reason': '...',
                    'reg20': 2.5,
                    'reg40': 1.5,
                }
            dry_run: 是否只计算不下单

        Returns:
            {
                'ok': True/False,
                'account_id': ...,
                'action': 'BUY/ADD/REDUCE/CLEAR/NO_ACTION',
                'code': ...,
                'shares': ...,
                'price': ...,
                'reason': ...,
                'status': 'EXECUTED'/'SKIPPED',
                'new_nav': ...,
            }
        """
        # 1. 加载账户
        acct = self.store.load(account_id)
        if not acct:
            return {'ok': False, 'error': f'账户 {account_id} 不存在', 'action': 'ERROR'}

        sig_type = signal.get('type', '').upper()
        code = signal.get('code', '')
        name = signal.get('name', '')
        score = signal.get('score', 0)
        reason = signal.get('reason', '')

        # 获取最新价格（统一缓存，盘中实时价，盘后DB兜底）
        price = self._get_price(code)
        if not price or price <= 0:
            return {'ok': False, 'error': f'{code} 获取价格失败', 'action': 'ERROR'}

        pos = acct.get_position(code)

        # 3. 根据信号类型执行
        if sig_type in ('BUY', 'NEW'):
            return self._do_buy(acct, code, name, price, score, reason, dry_run)
        elif sig_type == 'ADD':
            return self._do_add(acct, code, name, price, score, reason, dry_run)
        elif sig_type == 'REDUCE':
            return self._do_reduce(acct, code, name, price, score, reason, pos, dry_run)
        elif sig_type == 'CLEAR':
            return self._do_clear(acct, code, name, price, score, reason, pos, dry_run)
        elif sig_type == 'HOLD':
            return {
                'ok': True, 'account_id': account_id,
                'action': 'HOLD', 'code': code, 'name': name,
                'price': round(price, 2), 'shares': 0,
                'reason': reason, 'status': 'NO_ACTION',
                'new_nav': acct.total_nav({code: price}),
            }
        else:
            return {'ok': False, 'error': f'未知信号类型: {sig_type}', 'action': 'ERROR'}

    def execute_all_signals(self, account_id: str, signals: dict, dry_run: bool = False) -> dict:
        """
        批量执行一个账户的所有信号（持仓股信号 + 新候选买入信号）。
        按评分高低排序，先执行高优先级信号。

        关键：全程使用同一个 acct 对象，避免 execute_signal 每次重新 load 导致状态丢失。

        Args:
            account_id: 账户ID
            signals: {'held': [...], 'new_candidates': [...]}
            dry_run: 是否只计算不下单

        Returns:
            {
                'ok': True/False,
                'results': [...],
                'summary': {...},
            }
        """
        acct = self.store.load(account_id)
        if not acct:
            return {'ok': False, 'error': f'账户 {account_id} 不存在'}

        results = []
        all_signals = []

        # 收集所有信号
        for s in signals.get('held', []):
            all_signals.append({
                'type': s['type'],
                'code': s['code'],
                'name': s.get('name', ''),
                'score': s.get('score', 0),
                'reason': s.get('reason', ''),
                'reg20': s.get('reg20', 0),
                'reg40': s.get('reg40', 0),
            })

        for s in signals.get('new_candidates', []):
            all_signals.append({
                'type': 'BUY',
                'code': s['code'],
                'name': s.get('name', ''),
                'score': s.get('score', 0),
                'reason': f'新候选买入 评分{int(s.get("score",0))}',
                'reg20': s.get('reg20', 0),
                'reg40': s.get('reg40', 0),
            })

        # 按信号类型优先级排序：先减仓/清仓释放仓位和现金，再加仓，再买入，持有最后
        TYPE_ORDER = {'CLEAR': 0, 'REDUCE': 1, 'ADD': 2, 'BUY': 3, 'NEW': 3, 'HOLD': 4}
        all_signals.sort(key=lambda x: (TYPE_ORDER.get(x.get('type', 'HOLD'), 9), -x.get('score', 0)))

        # 收集所有需要价格的code
        all_codes = list(set(s['code'] for s in all_signals))
        # 批量预取价格（一次网络请求，缓存所有结果）
        self._batch_get_prices(all_codes)

        for sig in all_signals:
            result = self._execute_signal_on_acct(acct, sig, dry_run)
            results.append(result)
            if not dry_run:
                # 每个信号执行后立即保存，保持同一个 acct 对象
                self.store.save(acct)

        # 统计
        executed = [r for r in results if r.get('status') == 'EXECUTED']
        skipped = [r for r in results if r.get('status') == 'NO_ACTION']
        dry_run_results = [r for r in results if r.get('status') == 'DRY_RUN']
        errors = [r for r in results if r.get('status') == 'ERROR']

        return {
            'ok': True,
            'account_id': account_id,
            'results': results,
            'summary': {
                'total': len(all_signals),
                'executed': len(executed),
                'skipped': len(skipped),
                'dry_run': len(dry_run_results),
                'errors': len(errors),
            },
        }

    def _execute_signal_on_acct(self, acct, signal: dict, dry_run: bool = False) -> dict:
        """
        在已加载的 acct 对象上执行一个信号（不重新 load）。
        供 execute_all_signals 内部使用，确保状态持续累积。
        """
        account_id = acct.id
        sig_type = signal.get('type', '').upper()
        code = signal.get('code', '')
        name = signal.get('name', '')
        score = signal.get('score', 0)
        reason = signal.get('reason', '')

        price = self._get_price(code)
        if not price or price <= 0:
            return {'ok': False, 'error': f'{code} 获取价格失败', 'action': 'ERROR'}

        pos = acct.get_position(code)

        if sig_type in ('BUY', 'NEW'):
            return self._do_buy(acct, code, name, price, score, reason, dry_run)
        elif sig_type == 'ADD':
            return self._do_add(acct, code, name, price, score, reason, dry_run)
        elif sig_type == 'REDUCE':
            return self._do_reduce(acct, code, name, price, score, reason, pos, dry_run)
        elif sig_type == 'CLEAR':
            return self._do_clear(acct, code, name, price, score, reason, pos, dry_run)
        elif sig_type == 'HOLD':
            return {
                'ok': True, 'account_id': account_id,
                'action': 'HOLD', 'code': code, 'name': name,
                'price': round(price, 2), 'shares': 0,
                'reason': reason, 'status': 'NO_ACTION',
                'new_nav': acct.total_nav({code: price}),
            }
        else:
            return {'ok': False, 'error': f'未知信号类型: {sig_type}', 'action': 'ERROR'}

    def _do_buy(self, acct, code, name, price, score, reason, dry_run):
        """买入新股"""
        config = acct.config or {}
        max_positions = config.get('max_positions', 5)
        pos_sizing = config.get('position_sizing', {})

        # 检查仓位上限
        if acct.position_count >= max_positions:
            # 如果已有最大持仓，尝试替换评分最低的持仓
            min_score = float('inf')
            worst_code = None
            for p in acct.positions:
                if p.code != code:
                    # 查找该股的信号评分
                    pass
            # 直接返回跳过
            return {
                'ok': True, 'account_id': acct.id, 'action': 'BUY',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                'reason': f'仓位已满({max_positions}/{max_positions})',
                'status': 'SKIPPED', 'new_nav': acct.total_nav({code: price}),
            }

        # 计算买入金额 = 总净值 * 仓位比例
        total_nav = acct.total_nav()
        if score >= 70:
            pct = pos_sizing.get('score_high', {}).get('pct', 0.25)
        elif score >= 50:
            pct = pos_sizing.get('score_mid', {}).get('pct', 0.15)
        else:
            pct = pos_sizing.get('score_low', {}).get('pct', 0.10)

        buy_amount = total_nav * pct
        buy_amount = min(buy_amount, acct.cash * 0.95)  # 保留5%现金缓冲

        if buy_amount < 1000:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'BUY',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                'reason': f'买入金额不足({buy_amount:.0f}元)',
                'status': 'SKIPPED', 'new_nav': acct.total_nav({code: price}),
            }

        # 计算股数（A股必须是100股整数倍）
        shares = int(buy_amount / price / 100) * 100
        if shares <= 0:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'BUY',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                'reason': f'计算股数为0({buy_amount:.0f}/{price})',
                'status': 'SKIPPED', 'new_nav': acct.total_nav({code: price}),
            }

        cost = shares * price + shares * price * 0.001  # 含手续费滑点
        if cost > acct.cash:
            # 减少股数
            shares = int(acct.cash / price / 100) * 100
            if shares <= 0:
                return {
                    'ok': True, 'account_id': acct.id, 'action': 'BUY',
                    'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                    'reason': f'现金不足',
                    'status': 'SKIPPED', 'new_nav': acct.total_nav({code: price}),
                }
            cost = shares * price + shares * price * 0.001

        if dry_run:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'BUY',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': shares,
                'reason': reason,
                'status': 'DRY_RUN',
                'new_nav': acct.total_nav({code: price}),
            }

        # 执行买入
        total_cost = shares * price
        fee = total_cost * 0.0003  # 手续费
        slippage_cost = total_cost * 0.005  # 滑点
        actual_cost = total_cost + fee + slippage_cost

        pos = Position(
            code=code, name=name, shares=shares,
            avg_cost=round(price * (1 + (fee + slippage_cost) / total_cost), 2),
            buy_date=datetime.now().strftime('%Y-%m-%d'),
            peak_price=price,
            total_cost=round(actual_cost, 2),
        )
        acct.add_position(pos)
        acct.cash = round(acct.cash - actual_cost, 2)

        # 记录交易
        trade = acct.trades[-1] if acct.trades else None
        acct.trades.append(
            type('Trade', (), {
                'to_dict': lambda self: {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'action': '买入', 'code': code, 'name': name,
                    'price': round(price, 2), 'shares': shares,
                    'amount': round(actual_cost, 2),
                    'reason': reason, 'signal_score': score,
                }
            })()
        )

        # 记录流水
        self.trade_log.record_buy(
            acct.id, code, name, shares, price, actual_cost,
            signal_score=score, reason=reason,
        )

        return {
            'ok': True, 'account_id': acct.id, 'action': 'BUY',
            'code': code, 'name': name, 'price': round(price, 2),
            'shares': shares, 'cost': round(actual_cost, 2),
            'reason': reason, 'status': 'EXECUTED',
            'new_nav': acct.total_nav(),
        }

    def _do_add(self, acct, code, name, price, score, reason, dry_run):
        """加仓"""
        pos = acct.get_position(code)
        if not pos:
            return {'ok': False, 'error': f'{code} 不在持仓中', 'action': 'ERROR'}

        total_nav = acct.total_nav()
        config = acct.config or {}
        pos_sizing = config.get('position_sizing', {})

        # 计算加仓金额
        if score >= 70:
            pct = pos_sizing.get('score_high', {}).get('pct', 0.25)
        else:
            pct = pos_sizing.get('score_mid', {}).get('pct', 0.15)

        target_value = total_nav * pct
        current_value = pos.shares * pos.avg_cost
        add_amount = min(target_value - current_value, acct.cash * 0.95)

        if add_amount < 1000:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'ADD',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                'reason': '加仓金额不足', 'status': 'SKIPPED',
                'new_nav': acct.total_nav({code: price}),
            }

        shares = int(add_amount / price / 100) * 100
        if shares <= 0:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'ADD',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                'reason': '计算股数为0', 'status': 'SKIPPED',
                'new_nav': acct.total_nav({code: price}),
            }

        cost = shares * price + shares * price * 0.001
        if cost > acct.cash:
            shares = int(acct.cash / price / 100) * 100
            if shares <= 0:
                return {
                    'ok': True, 'account_id': acct.id, 'action': 'ADD',
                    'code': code, 'name': name, 'price': round(price, 2), 'shares': 0,
                    'reason': '现金不足', 'status': 'SKIPPED',
                    'new_nav': acct.total_nav({code: price}),
                }
            cost = shares * price + shares * price * 0.001

        if dry_run:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'ADD',
                'code': code, 'name': name, 'price': round(price, 2), 'shares': shares,
                'reason': reason, 'status': 'DRY_RUN',
                'new_nav': acct.total_nav({code: price}),
            }

        # 执行加仓（更新持仓）
        total_cost = shares * price
        fee = total_cost * 0.0003
        slippage_cost = total_cost * 0.005
        actual_cost = total_cost + fee + slippage_cost

        new_total_shares = pos.shares + shares
        new_total_cost = pos.shares * pos.avg_cost + actual_cost
        pos.avg_cost = round(new_total_cost / new_total_shares, 2)
        pos.shares = new_total_shares
        pos.peak_price = max(pos.peak_price, price)
        pos.total_cost = round(new_total_cost, 2)

        acct.cash = round(acct.cash - actual_cost, 2)

        # 记录交易
        acct.trades.append(
            type('Trade', (), {
                'to_dict': lambda self: {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'action': '加仓', 'code': code, 'name': name,
                    'price': round(price, 2), 'shares': shares,
                    'amount': round(actual_cost, 2),
                    'reason': reason, 'signal_score': score,
                }
            })()
        )

        self.trade_log.record_buy(
            acct.id, code, name, shares, price, actual_cost,
            signal_score=score, reason=f'加仓 {reason}',
        )

        return {
            'ok': True, 'account_id': acct.id, 'action': 'ADD',
            'code': code, 'name': name, 'price': round(price, 2),
            'shares': shares, 'cost': round(actual_cost, 2),
            'reason': reason, 'status': 'EXECUTED',
            'new_nav': acct.total_nav(),
        }

    def _do_reduce(self, acct, code, name, price, score, reason, pos, dry_run):
        """减仓"""
        if not pos or pos.shares <= 0:
            return {'ok': False, 'error': f'{code} 无持仓', 'action': 'ERROR'}

        # 减至50%仓位
        sell_shares = max(int(pos.shares * 0.5 / 100) * 100, 100)
        sell_shares = min(sell_shares, pos.shares)

        revenue = sell_shares * price
        fee = revenue * 0.0003
        slippage_cost = revenue * 0.005
        net_revenue = revenue - fee - slippage_cost

        # 盈亏计算
        sell_cost = pos.avg_cost * sell_shares
        pnl = net_revenue - sell_cost
        pnl_pct = (net_revenue / sell_cost - 1) * 100 if sell_cost > 0 else 0

        if dry_run:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'REDUCE',
                'code': code, 'name': name, 'price': round(price, 2),
                'shares': sell_shares, 'revenue': round(net_revenue, 2),
                'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2),
                'reason': reason, 'status': 'DRY_RUN',
                'new_nav': acct.total_nav({code: price}),
            }

        # 执行减仓
        acct.cash = round(acct.cash + net_revenue, 2)
        pos.shares -= sell_shares
        if pos.shares <= 0:
            acct.remove_position(code)
        pos.peak_price = max(pos.peak_price, price)

        # 记录交易
        acct.trades.append(
            type('Trade', (), {
                'to_dict': lambda self: {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'action': '减仓', 'code': code, 'name': name,
                    'price': round(price, 2), 'shares': sell_shares,
                    'amount': round(net_revenue, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'reason': reason, 'signal_score': score,
                }
            })()
        )

        self.trade_log.record_sell(
            acct.id, code, name, sell_shares, price, net_revenue,
            avg_cost=pos.avg_cost,
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            reason=f'减仓 {reason}',
        )

        return {
            'ok': True, 'account_id': acct.id, 'action': 'REDUCE',
            'code': code, 'name': name, 'price': round(price, 2),
            'shares': sell_shares, 'revenue': round(net_revenue, 2),
            'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2),
            'reason': reason, 'status': 'EXECUTED',
            'new_nav': acct.total_nav(),
        }

    def _do_clear(self, acct, code, name, price, score, reason, pos, dry_run):
        """清仓"""
        if not pos or pos.shares <= 0:
            return {'ok': False, 'error': f'{code} 无持仓', 'action': 'ERROR'}

        sell_shares = pos.shares
        revenue = sell_shares * price
        fee = revenue * 0.0003
        slippage_cost = revenue * 0.005
        net_revenue = revenue - fee - slippage_cost

        sell_cost = pos.avg_cost * sell_shares
        pnl = net_revenue - sell_cost
        pnl_pct = (net_revenue / sell_cost - 1) * 100 if sell_cost > 0 else 0

        if dry_run:
            return {
                'ok': True, 'account_id': acct.id, 'action': 'CLEAR',
                'code': code, 'name': name, 'price': round(price, 2),
                'shares': sell_shares, 'revenue': round(net_revenue, 2),
                'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2),
                'reason': reason, 'status': 'DRY_RUN',
                'new_nav': acct.total_nav({code: price}),
            }

        # 执行清仓
        acct.cash = round(acct.cash + net_revenue, 2)
        acct.remove_position(code)

        # 记录交易
        acct.trades.append(
            type('Trade', (), {
                'to_dict': lambda self: {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'action': '清仓', 'code': code, 'name': name,
                    'price': round(price, 2), 'shares': sell_shares,
                    'amount': round(net_revenue, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'reason': reason, 'signal_score': score,
                }
            })()
        )

        self.trade_log.record_sell(
            acct.id, code, name, sell_shares, price, net_revenue,
            avg_cost=pos.avg_cost,
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            reason=f'清仓 {reason}',
        )

        return {
            'ok': True, 'account_id': acct.id, 'action': 'CLEAR',
            'code': code, 'name': name, 'price': round(price, 2),
            'shares': sell_shares, 'revenue': round(net_revenue, 2),
            'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2),
            'reason': reason, 'status': 'EXECUTED',
            'new_nav': acct.total_nav(),
        }


if __name__ == '__main__':
    import json
    ex = Executor()

    print("=== 执行引擎测试 ===")

    # 测试买入（dry_run）
    result = ex.execute_signal('main', {
        'type': 'BUY', 'code': '600519', 'name': '贵州茅台',
        'score': 85.0, 'reason': '测试买入',
        'reg20': 2.5, 'reg40': 1.5,
    }, dry_run=True)
    print(f"买入(dry_run): {json.dumps(result, ensure_ascii=False, indent=2)}")

    # 测试清仓（dry_run）
    result = ex.execute_signal('main', {
        'type': 'CLEAR', 'code': '600519', 'name': '贵州茅台',
        'score': 20.0, 'reason': '清仓测试',
    }, dry_run=True)
    print(f"清仓(dry_run): {json.dumps(result, ensure_ascii=False, indent=2)}")

    # 测试批量执行
    signals = {
        'held': [
            {'type': 'HOLD', 'code': '600519', 'score': 60.0, 'reason': '维持', 'reg20': 0.5, 'reg40': 0.3},
        ],
        'new_candidates': [
            {'code': '605188', 'name': '国光连锁', 'score': 80.0, 'reg20': 3.0, 'reg40': 2.0, 'price': 11.87},
        ],
    }
    result = ex.execute_all_signals('main', signals, dry_run=True)
    print(f"批量(dry_run): {json.dumps(result, ensure_ascii=False, indent=2)}")
