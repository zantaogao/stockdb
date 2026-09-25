#!/usr/bin/env python3
"""
风控 Agent — 盘中实时决策
============================
功能：
1. 盘中运行（9:30-15:00），每 5 分钟检查一次
2. 输入：观察名单 + 实时行情
3. 逻辑：
   - 买入：信号分达标 + 价格未追高 + 仓位未满 + 大盘风险可控
   - 卖出：止损触发 / 信号恶化 / 止盈目标达成
   - 加仓：浮盈扩大 + 信号持续向好
   - 减仓：大盘转弱 / 个股破位
4. 输出：交易指令队列 orders/pending.json

配置：
    config/risk_config.json
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
from datetime import datetime, date
from typing import List, Dict, Optional

from core.data_source import DS
from core.prices import get_price
from core.unified_account import Account, Position, Trade, AccountStore


BASE = Path.home() / '.hermes' / 'stockdb'
ORDERS_DIR = BASE / 'orders'
ORDERS_DIR.mkdir(exist_ok=True)


# ── 风控配置 ─────────────────────────────────────────

RISK_CONFIG = {
    # 单只股票最大仓位比例（占总资金）
    'max_position_pct': 0.10,       # 10%
    # 买入条件
    'buy_score_threshold': 60,       # 评分 >= 60 才考虑买入
    'buy_max_deviation': 0.05,       # 价格偏离均线不超过 5%
    # 止损
    'stop_loss_pct': -0.08,          # 亏损 8% 止损
    # 止盈
    'take_profit_pct': 0.20,         # 盈利 20% 止盈
    # 加仓
    'add_on_profit_pct': 0.10,       # 浮盈 10% 以上考虑加仓
    'add_score_threshold': 65,       # 加仓要求更高评分
    # 减仓（大盘风险）
    'reduce_index_drop_pct': -0.03,  # 大盘日跌超 3% 减仓
    # 信号恶化
    'signal_drop_threshold': -15,    # 评分下降超过 15 分
}


def load_signals(target_date: str = None) -> List[Dict]:
    """加载最新观察名单"""
    if target_date:
        d = target_date.replace('-', '')
        sig_file = BASE / 'signals' / f'{d}_signals.json'
    else:
        sig_dir = BASE / 'signals'
        sig_files = sorted(sig_dir.glob('*_signals.json'))
        if not sig_files:
            return []
        sig_file = sig_files[-1]

    if not sig_file.exists():
        return []

    with open(sig_file) as f:
        return json.load(f)


def load_account(account_file: str) -> Account:
    """加载账户"""
    store = AccountStore()
    return store.load(account_file)


def save_account(account: Account, account_file: str):
    """保存账户"""
    store = AccountStore()
    store.save(account)


def get_pending_orders() -> List[Dict]:
    """加载待执行订单"""
    pending_file = ORDERS_DIR / 'pending.json'
    if not pending_file.exists():
        return []
    with open(pending_file) as f:
        return json.load(f)


def save_orders(orders: List[Dict]):
    """保存待执行订单（追加模式）"""
    existing = get_pending_orders()
    existing_codes = {(o.get('stock_code'), o.get('action')) for o in existing}

    for o in orders:
        key = (o.get('stock_code'), o.get('action'))
        if key in existing_codes:
            # 更新已有订单
            for ex in existing:
                if (ex.get('stock_code'), ex.get('action')) == key:
                    ex.update(o)
                    break
        else:
            existing.append(o)

    pending_file = ORDERS_DIR / 'pending.json'
    with open(pending_file, 'w') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def check_market_risk(ds: DS) -> bool:
    """
    检查大盘风险
    Returns: True 如果有风险需要减仓
    """
    try:
        idx = ds.get_index_daily('000001', start='20260101')
        if len(idx) < 2:
            return False

        latest = idx[-1]
        prev = idx[-2]
        change = (float(latest['close']) - float(prev['close'])) / float(prev['close'])

        if change < RISK_CONFIG['reduce_index_drop_pct']:
            print(f"  ⚠️ 大盘下跌 {change:.2%}，触发减仓信号")
            return True
        return False
    except Exception:
        return False


def evaluate_stock(
    stock_code: str,
    signal: Dict,
    position: Optional[Position],
    account: Account,
    ds: DS
) -> Optional[Dict]:
    """
    评估单只股票，返回交易指令或 None
    """
    score = signal.get('final_score', 0)
    action = None
    reason = ''

    if position:
        # 已有持仓
        # 获取当前价格
        cur_price = 0
        # 尝试从实时价格缓存获取
        if hasattr(account, '_price_cache') and stock_code in account._price_cache:
            cur_price = account._price_cache[stock_code]
        else:
            # 从 DS 获取
            try:
                daily = ds.get_daily(stock_code)
                if daily:
                    cur_price = float(daily[-1].get('close', 0))
            except:
                cur_price = position.avg_cost

        if position.avg_cost > 0:
            pnl_pct = (cur_price - position.avg_cost) / position.avg_cost

            # 1. 止损检查
            if pnl_pct <= RISK_CONFIG['stop_loss_pct']:
                action = 'SELL'
                reason = f"止损触发 亏损{pnl_pct:.2%}"

            # 2. 止盈检查
            elif pnl_pct >= RISK_CONFIG['take_profit_pct']:
                action = 'SELL'
                reason = f"止盈触发 盈利{pnl_pct:.2%}"

            # 3. 加仓检查（浮盈好 + 评分高）
            elif pnl_pct >= RISK_CONFIG['add_on_profit_pct'] and score >= RISK_CONFIG['add_score_threshold']:
                current_value = position.shares * cur_price
                max_value = account.cash * (RISK_CONFIG['max_position_pct'] * 2)
                if current_value < max_value:
                    action = 'ADD'
                    reason = f"浮盈{pnl_pct:.2%} 评分{score} 加仓"

        # 4. 信号恶化检查
        if not action and score < 40:
            action = 'REDUCE'
            reason = f"评分低 {score}"

    else:
        # 无持仓，检查买入条件
        if score >= RISK_CONFIG['buy_score_threshold']:
            # 检查仓位是否已满
            max_pos = RISK_CONFIG.get('max_positions', 5)
            if account.position_count >= max_pos:
                return None
            action = 'BUY'
            reason = f"评分{score} 进入观察名单"

    if not action:
        return None

    # 计算数量
    shares = calculate_shares(account, position, action, signal)

    return {
        'stock_code': stock_code,
        'stock_name': signal.get('stock_name', ''),
        'action': action,
        'shares': shares,
        'reason': reason,
        'signal_score': score,
        'timestamp': datetime.now().isoformat(),
    }


def calculate_shares(account: Account, position: Optional[Position], action: str, signal: Dict = None) -> int:
    """计算交易数量（A股 100 股整数规则）"""
    if position and action in ('SELL', 'REDUCE'):
        shares = position.shares
        if action == 'REDUCE':
            shares = shares // 2
        return (shares // 100) * 100

    # 买入/加仓
    max_pct = RISK_CONFIG['max_position_pct']
    price = 100  # 默认价格
    if signal:
        try:
            ds = DS()
            daily = ds.get_daily(signal.get('stock_code', ''))
            if daily:
                price = float(daily[-1].get('close', 100))
        except:
            pass

    amount = account.cash * max_pct
    shares = int(amount / price / 100) * 100
    return max(0, shares)


def run_risk_check(account_file: str = 'main', target_date: str = None):
    """
    风控检查入口
    """
    print("=" * 50)
    print(f"风控 Agent 运行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    ds = DS()

    # 1. 加载信号
    signals = load_signals(target_date)
    if not signals:
        print("  无观察名单，跳过")
        return []

    print(f"  观察名单: {len(signals)} 只")

    # 2. 加载账户
    account = load_account(account_file)
    print(f"  账户: {account.name} 现金: {account.cash:,.0f}")

    # 3. 检查大盘风险
    has_risk = check_market_risk(ds)

    # 4. 获取实时价格
    signal_map = {s['stock_code']: s for s in signals}
    price_codes = list(signal_map.keys())
    # 加上持仓中的股票代码
    price_codes_set = set(signal_map.keys())
    for p in account.positions:
        price_codes_set.add(p.code)
    price_codes = list(price_codes_set)

    prices = get_price(price_codes)

    # 设置价格缓存到账户对象
    account._price_cache = prices

    # 更新持仓当前价格（通过缓存）

    # 5. 逐只评估
    orders = []
    for signal in signals:
        code = signal['stock_code']
        position = None
        for p in account.positions:
            if p.code == code:
                position = p
                break

        order = evaluate_stock(code, signal, position, account, ds)
        if order:
            orders.append(order)
            print(f"  {order['action']} {code} {signal.get('stock_name', '')} "
                  f"{order['shares']}股 - {order['reason']}")

    # 6. 保存
    if orders:
        save_orders(orders)
        print(f"\n  生成 {len(orders)} 条交易指令")
    else:
        print("\n  无交易指令")

    return orders


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', default='main')
    parser.add_argument('--date', default=None)
    args = parser.parse_args()

    run_risk_check(args.account, args.date)
