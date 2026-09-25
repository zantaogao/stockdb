#!/usr/bin/env python3
"""验证 8/3 重跑：新权重生效 + 新旧对比"""
import sqlite3, glob, os, shutil

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
n = c.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260803'").fetchone()[0]
w = c.execute("SELECT COUNT(*) FROM watchlist WHERE REPLACE(scan_date,'-','')='20260803'").fetchone()[0]
print(f'8/3 signal_history: {n} 行, watchlist: {w} 行')

print('\n=== 新权重抽查（fusion_score vs 0.2/0.3/0.5 手算）===')
ok = 0
for r in c.execute("""SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history
    WHERE REPLACE(date,'-','')='20260803' ORDER BY fusion_score DESC LIMIT 5"""):
    calc = round(r[1]*0.2 + r[2]*0.3 + r[3]*0.5, 1)
    match = abs(r[4] - calc) < 0.05
    ok += match
    print(f'  {r[0]}: 手算={calc:+.1f} 表值={r[4]:+.1f} {"OK" if match else "MISMATCH"}')

# 旧权重对比（重跑前备份）
baks = sorted(glob.glob('/tmp/state.db.bak.*_pre_rescan'))
old_db = '/tmp/sb_old.db'
if baks:
    shutil.copy(baks[-1], old_db)
    c2 = sqlite3.connect(old_db)
    old = {r[0]: r[4] for r in c2.execute("""SELECT stock_code, fusion_score FROM signal_history
        WHERE REPLACE(date,'-','')='20260803'""").fetchall()}
    new = {r[0]: r[4] for r in c.execute("""SELECT stock_code, fusion_score FROM signal_history
        WHERE REPLACE(date,'-','')='20260803'""").fetchall()}
    common = set(old) & set(new)
    changed = sum(1 for k in common if abs(old[k] - new[k]) > 0.05)
    old_top10 = set(sorted(old, key=old.get, reverse=True)[:10])
    new_top10 = set(sorted(new, key=new.get, reverse=True)[:10])
    print(f'\n=== 新旧权重对比（{len(common)} 只共有）===')
    print(f'  分数变化: {changed} 只 ({changed/len(common)*100:.0f}%)')
    print(f'  旧 TOP10 与新 TOP10 重合: {len(old_top10 & new_top10)}/10')
    print(f'  新进 TOP10: {sorted(new_top10 - old_top10)}')
else:
    print('\n(未找到重跑前备份)')
print(f'\n新权重抽查匹配: {ok}/5')
