#!/usr/bin/env python3
"""
盘中风控检查脚本（cron每10分钟运行）
用法:
    python3 risk_check.py                          # 实时价格+持仓
    python3 risk_check.py --date 2026-06-23        # 用DB收盘价
"""
import sys, os, json
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from core.unified_account import AccountStore
from core.execution import ExecutionEngine

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='日期（回测用DB收盘价）')
    parser.add_argument('--quiet', action='store_true', help='只输出JSON')
    args = parser.parse_args()

    store = AccountStore()
    accts = store.get_all_accounts()
    exec_engine = ExecutionEngine()

    all_alerts = []
    all_data = {
        'timestamp': datetime.now().isoformat(),
        'accounts': {},
    }

    for aid, acct in accts.items():
        if not acct.positions:
            all_data['accounts'][aid] = {'status': 'empty', 'nav': acct.cash}
            continue

        codes = [p.code for p in acct.positions]
        price_map = exec_engine.fetch_prices(codes, ref_date=args.date)

        alerts = []
        for pos in acct.positions:
            price = price_map.get(pos.code, 0)
            if not price:
                continue
            pnl = (price / pos.avg_cost - 1) * 100
            drawdown = 0
            if pos.peak_price > 0:
                drawdown = (pos.peak_price - price) / pos.peak_price * 100

            alert = {
                'code': pos.code,
                'name': pos.name,
                'price': price,
                'pnl': pnl,
                'drawdown': drawdown,
                'peak': pos.peak_price,
                'shares': pos.shares,
            }

            # 检查止损
            hard_loss = acct.config.get('stop_loss_hard', -12.0)
            trailing = acct.config.get('stop_loss_trailing', 8.0)
            board_hard = -15.0 if pos.code.startswith(('300', '301', '688', '689')) else -12.0

            if pnl <= hard_loss:
                alert['alert'] = f"HARD STOP LOSS: {pnl:+.1f}%"
                alert['severity'] = 'CRITICAL'
                all_alerts.append(alert)
            elif pnl <= board_hard:
                alert['alert'] = f"BOARD STOP LOSS: {pnl:+.1f}%"
                alert['severity'] = 'WARNING'
                all_alerts.append(alert)
            elif pos.peak_price > 0 and drawdown >= trailing:
                alert['alert'] = f"TRAILING STOP: drawdown {drawdown:.1f}%"
                alert['severity'] = 'WARNING'
                all_alerts.append(alert)

        # 计算总持仓价值
        pos_value = sum(p.shares * price_map.get(p.code, p.avg_cost) for p in acct.positions)
        nav = acct.cash + pos_value
        ret = (nav / acct.initial_capital - 1) * 100

        all_data['accounts'][aid] = {
            'nav': round(nav, 2),
            'cash': round(acct.cash, 2),
            'positions': len(acct.positions),
            'returns': round(ret, 2),
            'alerts': alerts,
        }

    # 全局市场风险
    risk = exec_engine.market_risk_score()
    all_data['market_risk'] = risk

    # 输出
    if args.quiet:
        print(json.dumps(all_data, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"🔍 盘中风控检查 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")
        for aid, data in all_data['accounts'].items():
            if data.get('status') == 'empty':
                print(f"\n  {aid}: 空仓")
                continue
            print(f"\n  {aid} ({data['nav']:,.0f} 元):")
            print(f"    持仓: {data['positions']}只 | 现金: {data['cash']:,.0f} | 日收益: {data['returns']:+.2f}%")
            if data.get('alerts'):
                for a in data['alerts']:
                    sev = '🔴' if a.get('severity') == 'CRITICAL' else '🟡'
                    print(f"    {sev} {a['code']} {a['name']}: {a['alert']}")
        print(f"\n🌍 市场风险: {risk.get('score', 0):.2f} ({risk.get('label', '?')})")
        if all_alerts:
            print(f"\n⚠️ 共 {len(all_alerts)} 条告警")
        else:
            print(f"\n✅ 所有持仓正常")

    return all_data

if __name__ == '__main__':
    main()
