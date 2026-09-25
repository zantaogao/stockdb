#!/usr/bin/env python3
"""测试 signal_agent 评分功能"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.signal_agent import scan_stock, get_all_stocks, run_scan

# 测试 1 只
print("测试单只股票评分:")
s = {'stock_code': '600519', 'stock_name': '贵州茅台', 'industry': '白酒', 'board': '主板'}
result = scan_stock(s)
if result:
    print(f"  {s['stock_code']} {s['stock_name']} score={result['final_score']}")
    for k, v in result.items():
        print(f"    {k}: {v}")
else:
    print("  SKIP (数据不足)")

print("\n✅ 测试完成")
