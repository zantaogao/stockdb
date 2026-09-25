#!/usr/bin/env python3
"""核查 09:45 cmmr 跳拍是否漏掉真实风控动作：14 只持仓 vs 止损线/峰值回撤。"""
import sqlite3, os, sys
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
from core.prices import fetch_prices_batch

LED = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'))
rows = LED.execute(
    "SELECT code,name,shares,avg_cost,peak_price,stop_loss FROM strategy_positions WHERE account_id='cmmr'"
).fetchall()
codes = [r[0] for r in rows]
px = fetch_prices_batch(codes)
print(f"取价成功 {len(px)}/{len(codes)}")
n_breach = 0
for code, name, sh, cost, peak, sl in rows:
    p = px.get(code)
    if p is None:
        print(f"  {code} {name}: 无实时价")
        continue
    pnl = (p / cost - 1) * 100
    dd = (p / peak - 1) * 100 if peak else 0
    flag = ''
    if sl and p <= sl:
        flag = '  ← 跌破止损线'
        n_breach += 1
    print(f"  {code} {name}: 现价{p:.2f} 成本{cost:.2f} 浮盈{pnl:+.1f}% 距峰值{dd:+.1f}% 止损线{sl} {flag}")
print(f"\n实际跌破止损的持仓数: {n_breach}")
