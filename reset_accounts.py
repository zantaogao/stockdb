#!/usr/bin/env python3
"""清空持仓和交易流水，三账户只保留中长线"""
import json, shutil
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'

# 1. Reset main account
main = {
    "id": "main",
    "name": "中长线",
    "initial_capital": 1000000.0,
    "cash": 1000000.0,
    "positions": [],
    "trades": [],
    "nav_history": [],
    "config": {
        "initial_capital": 1000000.0,
        "max_positions": 5,
        "min_cash_reserve": 10000.0,
        "buy_score_threshold": 5.0,
        "buy_score_col": "reg20",
        "buy_max_upside_deviation": 25,
        "position_sizing": {
            "score_high": {"min": 12.0, "pct": 0.25},
            "score_mid": {"min": 8.0, "pct": 0.15},
            "score_low": {"min": 5.0, "pct": 0.10}
        },
        "stop_loss_hard": -12.0,
        "stop_loss_trailing": 8.0,
        "take_profit": 25.0,
        "signal_sell_threshold": -2.0,
        "market_risk_enabled": True,
        "max_same_industry": 2,
        "annual_trading_days": 242
    },
    "created_at": "2026-06-28",
    "updated_at": "2026-06-28"
}

main_path = BASE / 'sim_accounts' / 'main.json'
main_path.parent.mkdir(parents=True, exist_ok=True)
main_path.write_text(json.dumps(main, ensure_ascii=False, indent=2), encoding='utf-8')
print("✅ main 重置: 现金100万, 持仓0, 交易0")

# 2. Delete short/sim account files
for f in ['short.json', 'sim.json']:
    p = BASE / 'sim_accounts' / f
    if p.exists():
        p.unlink()
        print(f"  已删: sim_accounts/{f}")

# 3. Delete old-format files
for f in ['short_account.json', 'sim_state.json']:
    p = BASE / f
    if p.exists():
        bak = p.with_suffix('.json.bak')
        if not bak.exists():
            shutil.copy2(p, bak)
        p.unlink()
        print(f"  已删: {f} (备份→{bak.name})")

# 4. Sync account.json (old main format)
old_main = {
    "initial_capital": 1000000.0,
    "cash": 1000000.0,
    "positions": [],
    "trades": [],
    "nav_history": []
}
(BASE / 'account.json').write_text(
    json.dumps(old_main, ensure_ascii=False, indent=2), encoding='utf-8')
print("✅ account.json 已同步")

# 5. Clear trade logs
trades_dir = BASE / 'trades'
if trades_dir.exists():
    for sub in list(trades_dir.iterdir()):
        if sub.is_dir():
            for f in sub.iterdir():
                f.unlink()
            sub.rmdir()
    print("✅ 交易流水已清空")

# 6. Clear orders
orders_dir = BASE / 'orders'
if orders_dir.exists():
    shutil.rmtree(orders_dir)
    orders_dir.mkdir()
    print("✅ orders 已清空")

print("\n🎯 完成：仅保留 main（中长线100万），持仓/NAV/交易流水全部重置")
