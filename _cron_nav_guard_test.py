#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 strategy_accounts_daily 异常值防护逻辑（不真跑交易，直接测 run_day 的防护段）"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))

# 模拟 run_day 的防护逻辑（与脚本内一致）
def guard(daily_ret, mkt_ret, aid):
    nav_ok = abs(daily_ret) <= 30
    if not nav_ok:
        print(f"  ⚠️ {aid} daily_ret={daily_ret:.2f}% 异常（实时价瞬变），本次 NAV 不落库（交易已保存）")
    if mkt_ret is not None and abs(mkt_ret) > 30:
        print(f"  ⚠️ {aid} market_ret={mkt_ret:.2f}% 异常（指数实时价瞬变），用 0 替代")
        mkt_ret = 0.0
    return nav_ok, mkt_ret

print("=== 测试用例 ===")
cases = [
    ("正常日收益", 2.44, 0.70),
    ("正常负收益", -2.54, -1.00),
    ("异常日收益 +224%", 224.0, 0.70),
    ("异常日收益 -254%", -254.0, -1.00),
    ("异常 market_ret -99.85%", 1.15, -99.85),
    ("边界 +30%", 30.0, 30.0),
    ("边界 -30%", -30.0, -30.0),
]
for name, dr, mr in cases:
    nav_ok, mr2 = guard(dr, mr, "test")
    status = "✅ 写入" if nav_ok else "🚫 拦截(不写NAV)"
    mr_s = f"market_ret={mr2:.2f}%" if mr2 != mr else f"market_ret={mr}% (原样)"
    print(f"  [{name}] daily_ret={dr:>7.2f}% → {status} | {mr_s}")
print("\n预期: 正常/边界值写入, +224%/-254% 拦截, -99.85% 归零")
