"""只读核查（11:05 tick）：cmmr_fusion 本轮是否再缺价、落库 NAV 是否实时价口径。
1) 用脚本自身价格路径 fetch_prices_batch 拉它今日持仓
2) 与 ledger.db strategy_accounts 今日 pos_value 对账
3) 缺价只数统计
"""
import os, sys, sqlite3, time

SD = os.path.expanduser("~/.hermes/stockdb")
sys.path.insert(0, SD)
os.chdir(SD)

c = sqlite3.connect(os.path.join(SD, "ledger.db"))
cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_positions)")]
print("strategy_positions cols:", cols)
rows = c.execute("SELECT code, shares FROM strategy_positions WHERE account_id='cmmr_fusion'").fetchall()
codes = [r[0] for r in rows]
print("持仓数:", len(codes))

from core.prices import fetch_prices_batch  # noqa
t0 = time.time()
px = fetch_prices_batch(codes)
print(f"[fetch_prices_batch] {len(px)}/{len(codes)} in {time.time()-t0:.2f}s 缺:",
      [x for x in codes if x not in px])

pos_live = 0.0
for code, sh in rows:
    p = px.get(code)
    if p:
        pos_live += sh * float(p.get("price") if isinstance(p, dict) else p)
print("按实时价市值 =", round(pos_live, 2))

r = c.execute("SELECT date,cash,pos_value,nav,daily_ret FROM strategy_accounts "
              "WHERE account_id='cmmr_fusion' AND date='20260915'").fetchone()
print("落库行:", r)
if r:
    print("落库 pos_value =", r[2], " 实时价市值 =", round(pos_live, 2),
          " 差 =", round(r[2] - pos_live, 2))

avg = c.execute("SELECT SUM(shares*avg_cost) FROM strategy_positions WHERE account_id='cmmr_fusion'").fetchone()[0]
print("成本价市值 =", round(avg, 2), " (若落库≈此值=缺价兜底)")
