#!/usr/bin/env python3
"""验证 fusion_center 稳健 z 改动: 重算 8/7 信号, 对比新旧分布 2026-08-08"""
import sqlite3, subprocess, sys, math

STATE = '/Users/zantao/.hermes/stockdb/state.db'

# 1. 备份旧信号（8/7 行）
s = sqlite3.connect(STATE)
old = s.execute("SELECT stock_code, score, signal FROM fusion_center_signals WHERE REPLACE(date,'-','')='20260807'").fetchall()
print(f"旧信号 8/7: {len(old)} 行")
old_score = {r[0]: r[1] for r in old}
old_sig = {r[0]: r[2] for r in old}
s.close()

# 2. 重算（稳健 z 版）
r = subprocess.run([sys.executable, '-B', 'scripts/fusion_center_engine.py', '20260807'],
                   capture_output=True, timeout=300, cwd='/Users/zantao/.hermes/stockdb')
print(r.stdout.decode()[-800:])
if r.returncode != 0:
    print('重算失败:', r.stderr.decode()[-500:])
    sys.exit(1)

# 3. 新信号对比
s = sqlite3.connect(STATE)
new = s.execute("SELECT stock_code, score, signal FROM fusion_center_signals WHERE REPLACE(date,'-','')='20260807'").fetchall()
s.close()
new_score = {r[0]: r[1] for r in new}
new_sig = {r[0]: r[2] for r in new}
print(f"新信号 8/7: {len(new)} 行")

# 4. 对比
common = set(old_score) & set(new_score)
chg = sum(1 for c in common if abs(old_score[c] - new_score[c]) > 1e-9)
print(f"\n分数变化: {chg}/{len(common)} 只 ({chg/len(common)*100:.1f}%)")
diffs = [new_score[c] - old_score[c] for c in common]
if diffs:
    print(f"分数差: 中位 {sorted(diffs)[len(diffs)//2]:+.4f}, 最大 {max(abs(d) for d in diffs):.4f}")

# 旧版(原z)分数分布 vs 新版
def stats(vals):
    vs = sorted(vals)
    n = len(vs)
    return (vs[n//2], vs[0], vs[-1], sum((v - sum(vs)/n)**2 for v in vs)/n ** 0.5)
o, nn = list(old_score.values()), list(new_score.values())
print(f"\n分数分布 旧版: 中位 {sorted(o)[len(o)//2]:.4f}  范围 [{min(o):.4f}, {max(o):.4f}]  std={__import__('statistics').pstdev(o):.4f}")
print(f"分数分布 新版: 中位 {sorted(nn)[len(nn)//2]:.4f}  范围 [{min(nn):.4f}, {max(nn):.4f}]  std={__import__('statistics').pstdev(nn):.4f}")
print("区分度(std) 新版/旧版 =", round(__import__('statistics').pstdev(nn)/__import__('statistics').pstdev(o), 2))

# 5. 信号分级变化
from collections import Counter
oc, nc = Counter(old_sig.values()), Counter(new_sig.values())
print(f"\n信号分布 旧版: {dict(oc)}")
print(f"信号分布 新版: {dict(nc)}")

# 6. top10（强买内 score 前10）变化
old_top = sorted([(r[0], old_score[r[0]]) for r in old if old_sig[r[0]] == '强买'], key=lambda x: -x[1])[:10]
new_top = sorted([(r[0], new_score[r[0]]) for r in new if new_sig[r[0]] == '强买'], key=lambda x: -x[1])[:10]
print(f"\n旧版 Top10: {[c for c,_ in old_top]}")
print(f"新版 Top10: {[c for c,_ in new_top]}")
ov = {c for c,_ in old_top} & {c for c,_ in new_top}
print(f"Top10 重叠: {len(ov)}/10")

# 7. 正常股票区分度: 排除尾部 5% 后, 新版 z 是否比旧版展开（不被离群压扁）
import statistics
def mid80_std(vals):
    vs = sorted(vals)
    n = len(vs)
    mid = vs[int(n*0.05):int(n*0.95)]
    return statistics.pstdev(mid)
o80, n80 = mid80_std([old_score[r[0]] for r in old]), mid80_std([new_score[r[0]] for r in new])
print(f"中间80%股票的分 std: 旧版 {o80:.4f} → 新版 {n80:.4f} (x{n80/o80:.2f})")
print("(中间80% = 排除两端离群的正常股票, std 大 = 分数拉开 = 区分度好)")
