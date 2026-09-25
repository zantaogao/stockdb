#!/usr/bin/env python3
# 策略账户日更 tick 复核 (20260915 14:35 tick)
import sqlite3, duckdb, json, os, glob, datetime

SB = os.path.expanduser("~/.hermes/stockdb")
today = "20260915"

print("=== 1. strategy_accounts 各账户最新NAV日期 ===")
c = sqlite3.connect(os.path.join(SB, "ledger.db"))
for acc, mx, n, nav in c.execute(
    "SELECT account_id, MAX(date), COUNT(*), MAX(nav) FROM strategy_accounts GROUP BY account_id ORDER BY account_id"):
    last = c.execute("SELECT nav,daily_ret,n_pos,cash,pos_value FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1", (acc,)).fetchone()
    print(f"  {acc:14s} last={mx} rows={n:3d} nav={last[0]:,.0f} ret={last[1]} n_pos={last[2]} cash={last[3]:,.0f}")

print("\n=== 2. strategy_accounts_meta (cash 一致性) ===")
for r in c.execute("SELECT account_id, name, cash, updated_at FROM strategy_accounts_meta ORDER BY account_id"):
    print(f"  {r[0]:14s} {r[1]:12s} cash={r[2]:,.1f} updated={r[3]}")

print("\n=== 3. holdings vs strategy_positions (今日有交易的账户) ===")
for acc in ("cmmr", "cmmr_fusion", "fusion_center", "center_dual", "agent_auto"):
    hp = c.execute("SELECT COUNT(*), SUM(shares*avg_cost) FROM strategy_positions WHERE account_id=?", (acc,)).fetchone()
    print(f"  {acc:14s} strategy_positions={hp[0]}条 成本额={hp[1] or 0:,.0f}")

print("\n=== 4. 冷却/止盈禁买 今日写入 ===")
for r in c.execute("SELECT * FROM trade_cooldown WHERE REPLACE(cooldown_end,'-','')>=? OR REPLACE(start_date,'-','')=? ORDER BY account_id", (today, today)):
    print("  cooldown:", r)
for r in c.execute("SELECT * FROM trade_tp_ban"):
    print("  tp_ban:", r)

print("\n=== 5. crash_state / 异常痕迹 ===")
try:
    for r in c.execute("SELECT * FROM strategy_crash_state"):
        print("  crash:", r)
except Exception as e:
    print("  (no crash table rows)", e)

print("\n=== 6. sim_accounts JSON 与 DB 一致性 ===")
for f in sorted(glob.glob(os.path.join(SB, "sim_accounts", "*.json"))):
    name = os.path.basename(f)[:-5]
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f"  {name:14s} JSON解析失败: {e}")
        continue
    jnav = d.get("nav") or d.get("total_value")
    jcash = d.get("cash")
    holds = d.get("holdings") or []
    row = c.execute("SELECT nav, cash FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1", (name,)).fetchone()
    print(f"  {name:14s} mtime={datetime.datetime.fromtimestamp(os.path.getmtime(f)):%m-%d %H:%M} json_nav={jnav} json_cash={jcash} holds={len(holds)} | db_nav={row[0] if row else None} db_cash={row[1] if row else None}")

print("\n=== 7. 锁文件 ===")
lk = "/tmp/strategy_accounts_daily.lock"
if os.path.isdir(lk):
    print("  lock 存在, mtime =", datetime.datetime.fromtimestamp(os.path.getmtime(lk)))
else:
    print("  lock 已释放 (正常)")

print("\n=== 8. 今日中证1000 涨跌 (大跌市判定) ===")
try:
    con = duckdb.connect(os.path.join(SB, "tushare.db"), read_only=True)
    rows = con.execute("SELECT trade_date, close, pct_chg FROM index_daily WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 4").fetchall()
    for r in rows:
        print("  ", r)
except Exception as e:
    print("  index_daily 查询失败:", e)
