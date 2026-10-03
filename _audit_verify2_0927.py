#!/usr/bin/env python3
"""_audit_verify2_0927.py — 二轮复核：账实对账 + 38只漏因 + 死引用调用方（只读）"""
import sqlite3, os, subprocess
B = os.path.expanduser("~/.hermes/stockdb")
L = sqlite3.connect(f"file:{B}/ledger.db?mode=ro", uri=True)

print("== A. 持仓每股最新行市值 vs account_balance ==")
rows = L.execute("""SELECT code,shares,latest_price FROM holdings h WHERE status='hold'
    AND rowid=(SELECT rowid FROM holdings h2 WHERE h2.code=h.code AND h2.status='hold'
               ORDER BY update_time DESC)""").fetchall()
mval = sum(s*(p or 0) for _,s,p in rows)
cash, tv = L.execute("SELECT cash_balance,total_value FROM account_balance WHERE account_id='main'").fetchone()
print(f"   去重市值={mval:,.2f} 去重+现金={mval+cash:,.2f}  total_value落库={tv:,.2f}  差={tv-mval-cash:,.2f}")

print("== B. 301110 三行内容是否逐列相同 ==")
r = L.execute("""SELECT group_concat(DISTINCT buy_date||'|'||avg_cost||'|'||shares||'|'||latest_price)
    FROM holdings WHERE code='301110'""").fetchone()
print("   ", r)

print("== C. 9/24 有因子无信号 & 非ST非退 的漏因股票 ==")
S = sqlite3.connect(f"file:{B}/signals.db?mode=ro", uri=True)
miss = S.execute("""
  SELECT nf.stock_code FROM (SELECT DISTINCT stock_code FROM new_factors WHERE date='2026-09-24') nf
  LEFT JOIN (SELECT DISTINCT stock_code FROM fusion_3f_signals WHERE date='2026-09-24') f USING(stock_code)
  LEFT JOIN stock_basic sb ON sb.stock_code = nf.stock_code
  WHERE f.stock_code IS NULL AND (sb.name IS NULL OR (sb.name NOT LIKE '%ST%' AND sb.name NOT LIKE '%退%'))
  ORDER BY nf.stock_code""").fetchall()
print(f"   共 {len(miss)} 只:", [x[0] for x in miss])

print("== D. refresh_main_snapshot 引用检查 ==")
out = subprocess.run(["grep","-n","EA.BASE\\|BASE",os.path.join(B,"scripts/refresh_main_snapshot.py")],
                     capture_output=True, text=True).stdout
print(out or "   (无 BASE 引用)")

print("== E. trade_signals 写入方 ==")
out = subprocess.run(["grep","-rln","trade_signals","--include=*.py","--include=*.sh",B],
                     capture_output=True, text=True).stdout
print("\n".join(l for l in out.splitlines() if '.bak' not in l)[:800])
