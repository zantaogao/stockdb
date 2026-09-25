#!/usr/bin/env python3
"""重算 08-07 全市场评分（stk_factor 补拉后，因子数据修正）2026-08-08
只重算 20260807 一天：save_signals_all 幂等（DELETE+重插该日期行）。
不经过 __main__ 的 send_qq_report，避免重算时自动推送（推送单独走 push_top10.py）。
"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from agents.signal_agent import run_scan

watchlist = run_scan('20260807')
print(f"\n✅ 重算完成，观察名单 {len(watchlist)} 只")
