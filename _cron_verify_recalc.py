#!/usr/bin/env python3
"""验证重算结果: 旧(备份) vs 新(活库) 08-07 评分对比 2026-08-08"""
import sqlite3, sys

OLD = '/Users/zantao/.hermes/stockdb/state.db.bak.20260808_prerecalc'
NEW = '/Users/zantao/.hermes/stockdb/state.db'

old = sqlite3.connect(OLD)
new = sqlite3.connect(NEW)

def load(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()

# 1. 行数
o_n = load(old, "SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260807'")[0][0]
n_n = load(new, "SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260807'")[0][0]
print(f"signal_history 08-07 行数: 旧={o_n}, 新={n_n}")

# 2. 分数变化
o_rows = {r[0]: r[1] for r in load(old, "SELECT stock_code, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260807'")}
n_rows = {r[0]: r[1] for r in load(new, "SELECT stock_code, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260807'")}
common = set(o_rows) & set(n_rows)
diffs = [abs(o_rows[c] - n_rows[c]) for c in common]
changed = sum(1 for d in diffs if d > 0.05)
print(f"共同股票: {len(common)}, 分数变化>0.05: {changed} ({changed/len(common)*100:.1f}%)")
if diffs:
    diffs_sorted = sorted(diffs, reverse=True)
    print(f"变化幅度: max={diffs_sorted[0]:.2f}, p90={diffs_sorted[int(len(diffs_sorted)*0.9)]:.2f}, 中位={diffs_sorted[len(diffs_sorted)//2]:.2f}")

# 3. fusion_score Top10 对比
o_top = [r[0] for r in load(old, "SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')='20260807' AND fusion_score IS NOT NULL ORDER BY fusion_score DESC LIMIT 10")]
n_top = [r[0] for r in load(new, "SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')='20260807' AND fusion_score IS NOT NULL ORDER BY fusion_score DESC LIMIT 10")]
inter = set(o_top) & set(n_top)
print(f"\nfusion_score Top10: 旧={o_top}")
print(f"                 新={n_top}")
print(f"  重叠 {len(inter)}/10")

# 4. watchlist 对比
o_w = [r[0] for r in load(old, "SELECT ts_code FROM watchlist WHERE scan_date='20260807' ORDER BY score DESC")]
n_w = [r[0] for r in load(new, "SELECT ts_code FROM watchlist WHERE scan_date='20260807' ORDER BY score DESC")]
w_inter = set(o_w) & set(n_w)
print(f"\nwatchlist 08-07: 旧 {len(o_w)} 只, 新 {len(n_w)} 只, 重叠 {len(w_inter)}")
if o_w and n_w:
    print(f"  旧前5: {o_w[:5]}")
    print(f"  新前5: {n_w[:5]}")

# 5. final_score 分布（MODE=original 百分位）
o_f = [r[0] for r in load(old, "SELECT final_score FROM signal_history WHERE REPLACE(date,'-','')='20260807' AND final_score IS NOT NULL")]
n_f = [r[0] for r in load(new, "SELECT final_score FROM signal_history WHERE REPLACE(date,'-','')='20260807' AND final_score IS NOT NULL")]
import statistics
if o_f and n_f:
    print(f"\nfinal_score: 旧 mean={statistics.mean(o_f):.1f} 新 mean={statistics.mean(n_f):.1f}")

old.close(); new.close()
