"""
交易流水记录 v1
===================
每笔交易写入独立的流水文件，完整记录买入/卖出的所有细节。

设计：
- 每个账户独立目录: trades/{account_id}/
- 每条交易独立JSON文件，文件名含时间戳
- 同时维护一个 trades/{account_id}/all_trades.json 聚合文件
- 每笔交易记录：时间、方向、代码、名称、数量、价格、金额、手续费、滑点、PnL、信号分、原因、来源

用法：
    from core.trade_log import TradeLog
    log = TradeLog()
    log.record_buy(acct_id, code, name, shares, price, amount, reason, signal_score)
    log.record_sell(acct_id, code, name, shares, price, amount, pnl, pnl_pct, reason)
    log.get_all(acct_id) -> list
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

BASE = Path.home() / '.hermes' / 'stockdb'


class TradeLog:
    """交易流水记录器"""

    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir) if base_dir else BASE / 'trades'
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _account_dir(self, account_id: str) -> Path:
        d = self.base_dir / account_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ts_filename(self) -> str:
        return datetime.now().strftime('%Y%m%d_%H%M%S_%f')

    def record_buy(self, account_id: str, code: str, name: str,
                   shares: int, price: float, amount: float,
                   slippage: float = 0.005, fee_rate: float = 0.0003,
                   signal_score: float = None, reason: str = '',
                   market_condition: str = '',
                   risk_coef: float = 1.0,
                   position_pct: float = 0.25,
                   source: str = 'sim_engine') -> dict:
        """
        记录一笔买入交易。

        Returns: 流水记录dict
        """
        cost_base = shares * price
        slippage_cost = cost_base * slippage
        buy_fee = cost_base * fee_rate  # 买入手续费
        total_cost = cost_base + slippage_cost + buy_fee

        now = datetime.now()
        record = {
            'id': f"BUY-{self._ts_filename()}",
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'account_id': account_id,
            'action': 'BUY',
            'status': 'EXECUTED',
            'code': code,
            'name': name,
            'shares': shares,
            'price': round(price, 2),
            'cost_base': round(cost_base, 2),
            'slippage': slippage,
            'slippage_cost': round(slippage_cost, 2),
            'fee_rate': fee_rate,
            'fee': round(buy_fee, 2),
            'total_cost': round(total_cost, 2),
            'signal_score': signal_score,
            'reason': reason,
            'market_condition': market_condition,
            'risk_coef': risk_coef,
            'position_pct': position_pct,
            'source': source,
        }

        self._append_record(account_id, record)
        return record

    def record_sell(self, account_id: str, code: str, name: str,
                    shares: int, price: float, amount: float,
                    avg_cost: float = None,
                    slippage: float = 0.005, fee_rate: float = 0.0003,
                    pnl: float = None, pnl_pct: float = None,
                    reason: str = '',
                    signal_score: float = None,
                    hold_days: int = None,
                    source: str = 'sim_engine') -> dict:
        """
        记录一笔卖出交易。

        Returns: 流水记录dict
        """
        revenue_base = shares * price
        slippage_cost = revenue_base * slippage
        sell_fee = revenue_base * fee_rate
        net_revenue = revenue_base - slippage_cost - sell_fee

        cost_basis = avg_cost * shares if avg_cost else 0
        real_pnl = net_revenue - cost_basis if avg_cost else 0
        real_pnl_pct = (net_revenue / cost_basis - 1) * 100 if cost_basis > 0 else 0

        now = datetime.now()
        record = {
            'id': f"SELL-{self._ts_filename()}",
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'account_id': account_id,
            'action': 'SELL',
            'status': 'EXECUTED',
            'code': code,
            'name': name,
            'shares': shares,
            'price': round(price, 2),
            'avg_cost': round(avg_cost, 2) if avg_cost else None,
            'cost_basis': round(cost_basis, 2),
            'revenue_base': round(revenue_base, 2),
            'slippage': slippage,
            'slippage_cost': round(slippage_cost, 2),
            'fee_rate': fee_rate,
            'fee': round(sell_fee, 2),
            'net_revenue': round(net_revenue, 2),
            'pnl': round(real_pnl, 2),
            'pnl_pct': round(real_pnl_pct, 2) if pnl_pct is None else round(pnl_pct, 2),
            'signal_score': signal_score,
            'reason': reason,
            'hold_days': hold_days,
            'source': source,
        }

        self._append_record(account_id, record)
        return record

    def record_partial_sell(self, account_id: str, code: str, name: str,
                            shares_sold: int, price: float,
                            avg_cost: float,
                            slippage: float = 0.005, fee_rate: float = 0.0003,
                            hold_days: int = None,
                            reason: str = '') -> dict:
        """记录部分卖出（减仓），同时记录剩余持仓状态"""
        sold = self.record_sell(
            account_id, code, name, shares_sold, price,
            avg_cost=avg_cost, slippage=slippage, fee_rate=fee_rate,
            reason=reason, hold_days=hold_days, source='partial_sell'
        )
        return sold

    def _append_record(self, account_id: str, record: dict):
        """追加到聚合文件"""
        agg_path = self._account_dir(account_id) / 'all_trades.json'
        all_trades = []
        if agg_path.exists():
            try:
                all_trades = json.loads(agg_path.read_text(encoding='utf-8'))
            except:
                all_trades = []
        all_trades.append(record)
        agg_path.write_text(
            json.dumps(all_trades, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8'
        )

    def get_all(self, account_id: str) -> List[dict]:
        """获取账户所有交易记录"""
        agg_path = self._account_dir(account_id) / 'all_trades.json'
        if not agg_path.exists():
            return []
        try:
            return json.loads(agg_path.read_text(encoding='utf-8'))
        except:
            return []

    def get_by_date(self, account_id: str, date: str) -> List[dict]:
        """获取指定日期的交易记录"""
        return [t for t in self.get_all(account_id) if t.get('date') == date]

    def get_by_code(self, account_id: str, code: str) -> List[dict]:
        """获取某只股票的全部交易记录"""
        return [t for t in self.get_all(account_id) if t.get('code') == code]

    def get_summary(self, account_id: str) -> dict:
        """获取交易统计摘要"""
        trades = self.get_all(account_id)
        buys = [t for t in trades if t['action'] == 'BUY']
        sells = [t for t in trades if t['action'] == 'SELL']
        total_buys = sum(t.get('total_cost', 0) for t in buys)
        total_sells = sum(t.get('net_revenue', 0) for t in sells)
        total_pnl = sum(t.get('pnl', 0) for t in sells)
        wins = [t for t in sells if t.get('pnl', 0) > 0]
        losses = [t for t in sells if t.get('pnl', 0) <= 0]
        return {
            'total_trades': len(trades),
            'buys': len(buys),
            'sells': len(sells),
            'total_buy_cost': round(total_buys, 2),
            'total_sell_revenue': round(total_sells, 2),
            'realized_pnl': round(total_pnl, 2),
            'win_rate': len(wins) / max(len(sells), 1) * 100,
            'win_count': len(wins),
            'loss_count': len(losses),
        }

    def export_csv(self, account_id: str, path: str = None) -> str:
        """导出为CSV格式"""
        trades = self.get_all(account_id)
        if not trades:
            return ''

        if not path:
            path = str(self.base_dir / account_id / 'trades.csv')

        header = 'date,time,action,code,name,shares,price,cost_base,fee,slippage,pnl,pnl_pct,reason,signal_score,source\n'
        lines = [header]
        for t in trades:
            line = f'{t["date"]},{t["time"]},{t["action"]},{t["code"]},{t["name"]},{t["shares"]},{t["price"]},{t.get("cost_base",0):.2f},{t.get("fee",0):.2f},{t.get("slippage",0)},{t.get("pnl",0):.2f},{t.get("pnl_pct",0):.2f},"{t.get("reason","")}",{t.get("signal_score","")},{t.get("source","")}\n'
            lines.append(line)

        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return path


if __name__ == '__main__':
    import json as _json
    log = TradeLog()

    # 测试
    print("=== 交易流水测试 ===")
    log.record_buy('main', '600519', '贵州茅台',
                   shares=100, price=1600.0, amount=160000,
                   signal_score=85.5, reason='信号买入',
                   market_condition='震荡', risk_coef=0.65)

    log.record_sell('main', '600519', '贵州茅台',
                    shares=100, price=1650.0, amount=165000,
                    avg_cost=1600.0,
                    pnl=5000, pnl_pct=3.125,
                    reason='止盈卖出', hold_days=10,
                    signal_score=72.0)

    summary = log.get_summary('main')
    print(f"\n{json.dumps(summary, ensure_ascii=False, indent=2)}")

    all_trades = log.get_all('main')
    print(f"\n全部交易: {len(all_trades)} 笔")
    for t in all_trades:
        print(f'  [{t["action"]}] {t["code"]} {t["name"]} {t["shares"]}股 @ {t["price"]}')
