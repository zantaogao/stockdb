#!/usr/bin/env python3
"""模拟交易每日运行脚本"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.sim_engine import SimEngine

def main():
    ref_date = None
    for i, a in enumerate(sys.argv):
        if a == '--date' and i + 1 < len(sys.argv):
            ref_date = sys.argv[i + 1]

    engine = SimEngine()
    result = engine.run_daily(ref_date)
    print(f"\n📋 操作摘要")
    print(f"  买入: {len(result['buys'])}笔")
    print(f"  卖出: {len(result['sells'])}笔")
    print(f"  NAV: {result['nav']['nav']:,.0f}")
    print(f"  市场风险: {result['risk']['label']} ({result['risk']['score']:.2f})")

    # 显示绩效
    print()
    print(engine.performance_summary())

if __name__ == '__main__':
    main()
