#!/usr/bin/env python3
"""测试盘中决策逻辑（简化版，用 DB 收盘价）"""
import duckdb
from pathlib import Path
import json
from datetime import datetime

STATE_DB = Path.home() / '.hermes/stockdb' / 'state.db'
HOLDINGS_FILE = Path.home() / '.hermes/stockdb' / 'holdings.json'
PENDING_FILE = Path.home() / '.hermes/stockdb' / 'orders' / 'pending.json'

print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始决策...")

# 获取最新观察名单
conn = duckdb.connect(str(STATE_DB), read_only=True)
watch_rows = conn.execute("""
    SELECT w.ts_code, w.score 
    FROM watchlist w
    WHERE w.scan_date = (SELECT MAX(scan_date) FROM watchlist WHERE scan_date IS NOT NULL)
      AND w.status = 'pending'
    ORDER BY w.score DESC
    LIMIT 5
""").fetchall()
conn.close()

print(f"观察名单：{len(watch_rows)}只")
for r in watch_rows:
    print(f"  {r[0]} score={r[1]}")

# 获取持仓
holdings = json.loads(HOLDINGS_FILE.read_text()) if HOLDINGS_FILE.exists() else {'positions': []}
positions = [p for p in holdings.get('positions', []) if p.get('status') == 'hold']
print(f"\n持仓：{len(positions)}只")

# 简化：生成测试订单
signals = []
if watch_rows:
    # 取评分最高的 1 只买入
    code, score = watch_rows[0]
    signals.append({
        'stock_code': code,
        'action': 'BUY',
        'shares': 10000,
        'price': 10.0,  # 测试价
        'reason': f'测试买入 评分{score:.0f}',
        'signal_score': score
    })

# 写入 pending.json
if signals:
    PENDING_FILE.parent.mkdir(exist_ok=True)
    output = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'market_change': 0.5,
        'signals': signals
    }
    PENDING_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅ 生成 {len(signals)} 条订单 → {PENDING_FILE}")
    print(json.dumps(output, indent=2, ensure_ascii=False))
else:
    print("\n✓ 无新订单")
