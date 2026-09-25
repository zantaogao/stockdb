#!/usr/bin/env python3
"""存量持仓 target_price/stop_loss 回填 (2026-08-02)
规则:
1. 从 watchlist 取 status='bought' 且扫描日最接近 holdings.buy_date 的记录
2. 有 stop_loss/target_price 且 >0 → 回填
3. 无可用值 → stop_loss = round(avg_cost * 0.88, 2)（与硬止损 -12% 同口径），target_price 留空
先 dry-run 打印计划，--apply 才写库。
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'state.db'

APPLY = '--apply' in sys.argv

conn = sqlite3.connect(str(STATE_DB), timeout=15)
conn.execute("PRAGMA busy_timeout=15000")

holdings = conn.execute(
    "SELECT code, name, buy_date, avg_cost, target_price, stop_loss FROM holdings WHERE status='hold'"
).fetchall()

plan = []
for code, name, buy_date, cost, cur_tp, cur_sl in holdings:
    if cur_tp and cur_sl:
        continue  # 已有值不动
    # 统一日期为 YYYYMMDD
    bd = buy_date.replace('-', '') if buy_date else ''
    # watchlist 候选：bought 状态
    rows = conn.execute(
        "SELECT ts_code, stop_loss, target_price, scan_date FROM watchlist "
        "WHERE ts_code=? AND status='bought' AND (stop_loss>0 OR target_price>0)",
        (code,)
    ).fetchall()
    best = None
    if rows:
        # 选扫描日最接近买入日的记录（扫描应 <= 买入日，即扫描在前买入在后）
        best = min(rows, key=lambda r: abs(int((r[3] or '').replace('-', '')) - int(bd)) if bd else 0)
    if best:
        sl, tp = best[1], best[2]
        plan.append((code, name, cost, sl, tp, f"watchlist {best[3]}"))
    else:
        sl = round(cost * 0.88, 2)
        tp = None
        plan.append((code, name, cost, sl, tp, "无watchlist→成本×0.88"))

print(f"{'代码':<10}{'名称':<8}{'成本':>8}{'新止损':>10}{'新目标':>10}  来源")
for code, name, cost, sl, tp, src in plan:
    tp_s = f"{tp:.2f}" if tp else "空"
    print(f"{code:<10}{name:<8}{cost:>8.3f}{sl:>10.2f}{tp_s:>10}  {src}")

if not APPLY:
    print("\n[dry-run] 加 --apply 执行写入")
    conn.close()
    sys.exit(0)

# ── 执行写入 ──
n = 0
for code, name, cost, sl, tp, src in plan:
    if tp:
        conn.execute("UPDATE holdings SET stop_loss=?, target_price=? WHERE code=? AND status='hold'", (sl, tp, code))
    else:
        conn.execute("UPDATE holdings SET stop_loss=? WHERE code=? AND status='hold'", (sl, code))
    n += 1
conn.commit()

# ── 验证 ──
print(f"\n已回填 {n} 只，验证:")
for r in conn.execute("SELECT code, name, avg_cost, target_price, stop_loss FROM holdings WHERE status='hold'").fetchall():
    tp_s = f"{r[3]:.2f}" if r[3] else "空"
    sl_s = f"{r[4]:.2f}" if r[4] else "空"
    print(f"  {r[0]} {r[1]}: 成本{r[2]:.3f} 止损={sl_s} 目标={tp_s}")
conn.close()
