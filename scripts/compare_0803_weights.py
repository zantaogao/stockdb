#!/usr/bin/env python3
"""8/3 新旧权重评分对比"""
import sqlite3, statistics

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
c2 = sqlite3.connect('/tmp/state.db.bak.20260803_235044_pre_rescan')

old = {r[0]: r[4] for r in c2.execute("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260803'").fetchall()}
new = {r[0]: r[4] for r in c.execute("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260803'").fetchall()}
common = set(old) & set(new)
changed = sum(1 for k in common if abs(old[k] - new[k]) > 0.05)
old_top10 = set(sorted(old, key=old.get, reverse=True)[:10])
new_top10 = set(sorted(new, key=new.get, reverse=True)[:10])
print(f'共有 {len(common)} 只')
print(f'分数变化: {changed} 只 ({changed/len(common)*100:.0f}%)')
print(f'旧 TOP10 与新 TOP10 重合: {len(old_top10 & new_top10)}/10')
print(f'新进 TOP10: {sorted(new_top10 - old_top10)}')
print(f'跌出 TOP10: {sorted(old_top10 - new_top10)}')
diffs = [old[k] - new[k] for k in common]
print(f'分数变化分布: 均值 {statistics.mean(diffs):+.2f}, 中位 {statistics.median(diffs):+.2f}, 最大 {max(diffs):+.1f}, 最小 {min(diffs):+.1f}')
