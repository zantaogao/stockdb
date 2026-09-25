#!/usr/bin/env python3
"""
每日交易引擎运行脚本（cron调用入口）
用法:
    python3 run_trade_engine.py                  # 运行所有账户，实时价格
    python3 run_trade_engine.py --date 2026-06-23 # 回测特定日期
    python3 run_trade_engine.py --dry-run          # 仅计算，不保存
    python3 run_trade_engine.py --metrics          # 同时显示绩效报告
    python3 run_trade_engine.py --report           # 跨账户对比报告
    python3 run_trade_engine.py --health           # 数据健康检查
    python3 run_trade_engine.py --compat           # 兼容模式（仅sim账户）
"""
import sys, os
from pathlib import Path

BASE = Path(__file__).parent.parent.parent  # 从 cron/ 向上两层到 stockdb/
sys.path.insert(0, str(BASE))

import json
from datetime import datetime
from core.sim_engine import TradeEngine, cross_account_report, check_all

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='交易日期（回测）')
    parser.add_argument('--dry-run', action='store_true', help='仅计算，不保存')
    parser.add_argument('--metrics', action='store_true', help='显示绩效')
    parser.add_argument('--report', action='store_true', help='跨账户对比报告')
    parser.add_argument('--health', action='store_true', help='数据健康检查')
    parser.add_argument('--compat', action='store_true', help='兼容模式')
    args = parser.parse_args()

    if args.health:
        results = check_all()
        all_ok = True
        for k, v in results.items():
            status = '✅' if v['ok'] else '❌'
            print(f"{status} {k}: {v['message']}")
            if not v['ok']:
                all_ok = False
        sys.exit(0 if all_ok else 1)

    if args.report:
        print(cross_account_report())
        sys.exit(0)

    if args.compat:
        from core.sim_engine import SimEngine
        engine = SimEngine()
        engine.run_daily(ref_date=args.date, dry_run=args.dry_run)
        if args.metrics:
            print("\n" + engine.performance_summary())
        sys.exit(0)

    engine = TradeEngine()
    result = engine.run_daily(ref_date=args.date, dry_run=args.dry_run)

    if not result:
        print("\n⚠️ 未执行任何交易（无信号数据或无账户）")

    # 保存交易日志（用于通知）
    if result:
        log = {
            'timestamp': datetime.now().isoformat(),
            'date': args.date or datetime.now().strftime('%Y-%m-%d'),
            'results': {},
        }
        for aid, r in result.items():
            log['results'][aid] = {
                'nav': r.get('nav', {}),
                'buys': len(r.get('buys', [])),
                'sells': len(r.get('sells', [])),
            }
        log_path = BASE / 'daily_trade_log.json'
        log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))
        print(f"\n📝 日志已保存至 {log_path}")

    if args.metrics:
        print("\n" + engine.performance_summary())

    # 输出摘要到stdout（便于cron捕获）
    summary_lines = []
    for aid, r in result.items():
        nav = r.get('nav', {})
        summary_lines.append(
            f"{aid}: NAV={nav.get('nav', 0):,.0f} "
            f"(日收益{nav.get('returns', 0):+.2f}%) "
            f"买入{len(r.get('buys', []))} 卖出{len(r.get('sells', []))}笔"
        )
    print("\n" + " | ".join(summary_lines) if summary_lines else "无交易数据")


if __name__ == '__main__':
    main()
