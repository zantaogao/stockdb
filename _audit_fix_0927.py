#!/usr/bin/env python3
"""_audit_fix_0927.py — 执行 0927 全面审计的处置项（写库前已备份 /tmp/*.bak_pre0927audit）
1. holdings 加 UNIQUE(code,status) + 清 301110 重复行(留最新) + account_balance 纠偏(-73000)
2. signal_history 9831 行 dash 日期归一为 compact
3. health_check 模型白名单核对（v8 实际在位则不动，只报告）
"""
import sqlite3, os, json
B = os.path.expanduser("~/.hermes/stockdb")
now = "2026-09-27T23:30:00"

L = sqlite3.connect(f"{B}/ledger.db", timeout=30)
L.execute("PRAGMA foreign_keys=OFF")

# ── 1. 清重复（含 0925 遗留的已卖残留）：status='hold' 同 code 保留 update_time 最新一行 ──
n = L.execute("""DELETE FROM holdings WHERE status='hold'
    AND rowid NOT IN (
    SELECT rowid FROM holdings h WHERE h.rowid=(
        SELECT rowid FROM holdings h2 WHERE h2.code=h.code AND h2.status='hold'
        ORDER BY h2.update_time DESC LIMIT 1))""").rowcount
print("holdings 重复/残留行删除:", n)

# ── 2. 唯一约束（防再发）：用 SQL 文件走 sqlite CLI ──
import subprocess
r = subprocess.run(["sqlite3", f"{B}/ledger.db"], stdin=open(f"{B}/_audit_holdings_unique.sql"),
                   capture_output=True, text=True)
print("UNIQUE 约束重建:", "OK" if r.returncode == 0 else f"FAIL {r.stderr}")
if r.returncode != 0:
    raise SystemExit("约束重建失败，中止（此时重复行已删但未加约束）")

# ── 3. 总资产纠偏（现金 161.25 不动，只改虚高 73000）──
row = L.execute("SELECT cash_balance, total_value FROM account_balance WHERE account_id='main'").fetchone()
mval = L.execute("SELECT SUM(shares*latest_price) FROM holdings WHERE status='hold'").fetchone()[0]
true_total = round(row[0] + mval, 2)
L.execute("UPDATE account_balance SET total_value=?, last_update=? WHERE account_id='main'", (true_total, now))
print(f"account_balance: total {row[1]:,.2f} -> {true_total:,.2f} (市值复核 {mval:,.2f})")

# ── 4. position_peaks 复核 301110 ──
pk = L.execute("SELECT * FROM position_peaks WHERE code='301110'").fetchall()
print("301110 peak 行(留待下轮17:50重建):", pk)
L.commit()

# ── 5. 验证持仓加载端 ──
n_pos = L.execute("SELECT COUNT(*) FROM holdings WHERE status='hold'").fetchone()[0]
codes = L.execute("SELECT COUNT(DISTINCT code) FROM holdings WHERE status='hold'").fetchone()[0]
print(f"验证: hold 行数={n_pos} 去重code数={codes} (应相等)")
L.close()

# ── 6. signal_history 日期归一 ──
S = sqlite3.connect(f"{B}/signals.db", timeout=30)
dup = S.execute("""SELECT COUNT(*) FROM signal_history WHERE date LIKE '____-__-__'
    AND REPLACE(date,'-','')||'|'||stock_code IN (
    SELECT date||'|'||stock_code FROM signal_history WHERE date NOT LIKE '%-%')""").fetchone()[0]
print("dash 行与 compact 行同票同日重叠数:", dup)
n = S.execute("DELETE FROM signal_history WHERE date LIKE '____-__-__' AND REPLACE(date,'-','')||'|'||stock_code IN (SELECT date||'|'||stock_code FROM signal_history WHERE date NOT LIKE '%-%')").rowcount
print("先删重叠 dash 行:", n)
m = S.execute("UPDATE signal_history SET date=REPLACE(date,'-','') WHERE date LIKE '____-__-__'").rowcount
print("剩余 dash 归一为 compact:", m)
left = S.execute("SELECT COUNT(*) FROM signal_history WHERE date LIKE '____-__-__'").fetchone()[0]
print("验证 dash 残留:", left)
S.commit(); S.close()

# ── 7. health_check 白名单核对 ──
need = ['lgb_reg_10d_v8.txt','v10_v8_stats.json','lgb_reg_20d_v2.txt','v20_v2_stats.json',
        'lgb_reg_40d_v8.txt','v40_v8_stats.json','lgb_reg_etf_20d_v1.txt','v_etf_v1_stats.json']
miss = [f for f in need if not os.path.exists(f"{B}/models/{f}")]
print("生产实际链在位检查:", "全部在位" if not miss else f"缺 {miss}")
print("DONE_ALL")
