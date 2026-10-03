#!/usr/bin/env python3
"""_audit_verify_0927.py — 复核 harness 审计发现（列名已对 PRAGMA 校准；全程只读 mode=ro）"""
import sqlite3, os
B = os.path.expanduser("~/.hermes/stockdb")
L = sqlite3.connect(f"file:{B}/ledger.db?mode=ro", uri=True)
S = sqlite3.connect(f"file:{B}/signals.db?mode=ro", uri=True)

print("== 1. holdings 301110 逐行 ==")
for r in L.execute("SELECT rowid,code,name,status,buy_date,avg_cost,shares,latest_price,update_time FROM holdings WHERE code LIKE '301110%'").fetchall():
    print("  ", r)

print("== 2. holdings 重复签名 (code,status,shares 相同>1行) ==")
for r in L.execute("""SELECT code,shares,status,COUNT(*) c, GROUP_CONCAT(update_time,'|')
    FROM holdings GROUP BY code,status,shares HAVING c>1""").fetchall():
    print("  ", r)

print("== 3. 301110 trade_log 全史 ==")
for r in L.execute("SELECT id,trade_date,trade_time,direction,price,quantity,amount,strategy FROM trade_log WHERE code LIKE '301110%' ORDER BY trade_date").fetchall():
    print("  ", r)

print("== 4. execution_logs 结构+301110 ==")
cols = [c[1] for c in L.execute("PRAGMA table_info(execution_logs)").fetchall()]
print("   cols:", cols)
txtcol = next((c for c in cols if c in ("result","detail","output","message","payload","log")), None)
if txtcol:
    for r in L.execute(f"SELECT rowid,* FROM execution_logs WHERE {txtcol} LIKE '%301110%' ORDER BY rowid DESC LIMIT 3").fetchall():
        print("  ", str(r)[:280])

print("== 5. 市值口径差 ==")
tot_all = L.execute("SELECT SUM(shares), SUM(shares*latest_price) FROM holdings WHERE status='hold'").fetchone()
ded = L.execute("""SELECT SUM(shares), SUM(shares*latest_price) FROM holdings h WHERE status='hold'
    AND rowid=(SELECT rowid FROM holdings h2 WHERE h2.code=h.code AND h2.status='hold'
               ORDER BY update_time DESC LIMIT 1)""").fetchone()
print(f"   全行口径: {tot_all[0]}股 {tot_all[1]:,.0f}元")
print(f"   每code最新行: {ded[0]}股 {ded[1]:,.0f}元")

print("== 6. account_balance ==")
print("  ", L.execute("SELECT * FROM account_balance").fetchall())

print("== 7. position_peaks 有无 301110 ==")
print("  ", L.execute("SELECT * FROM position_peaks WHERE code LIKE '301110%'").fetchall())

print("== 8. signal_history 格式分布 ==")
print("   dash:", S.execute("SELECT COUNT(*),MIN(date),MAX(date) FROM signal_history WHERE date GLOB '____-__-__*'").fetchone())
print("   compact:", S.execute("SELECT COUNT(*),MIN(date),MAX(date) FROM signal_history WHERE date GLOB '________'").fetchone())

print("== 9. 9/24 有因子无信号股票（fusion 池 vs new_factors 池差集） ==")
try:
    cols_f = [c[1] for c in S.execute("PRAGMA table_info(fusion_3f_signals)").fetchall()]
    cols_n = [c[1] for c in S.execute("PRAGMA table_info(new_factors)").fetchall()]
    kc = 'stock_code' if 'stock_code' in cols_f else 'code'
    kn = 'stock_code' if 'stock_code' in cols_n else 'code'
    rows = S.execute(f"""SELECT nf.k FROM (SELECT DISTINCT {kn} k FROM new_factors WHERE date='2026-09-24') nf
        LEFT JOIN (SELECT DISTINCT {kc} k FROM fusion_3f_signals WHERE date='2026-09-24') f USING(k)
        WHERE f.k IS NULL""").fetchall()
    print(f"   差集 {len(rows)} 只, 样例:", [r[0] for r in rows[:12]])
except Exception as e:
    print("   fail:", e)

print("== 10. ic_daily 近6行 ==")
for r in S.execute("SELECT * FROM ic_daily ORDER BY rowid DESC LIMIT 6").fetchall():
    print("  ", str(r)[:200])
