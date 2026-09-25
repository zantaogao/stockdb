#!/usr/bin/env /usr/bin/python3 -B
"""10d生产top10 × clf10 影子意见"""
import sqlite3, duckdb
import numpy as np
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
sd = c.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0]
print("信号日:", sd)
top = c.execute("SELECT stock_code, stock_name, industry, reg10 FROM signal_history WHERE REPLACE(date,'-','')=? ORDER BY reg10 DESC LIMIT 10", (sd,)).fetchall()
clf = {str(k): float(v) for k, v in c.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd,)).fetchall()}
allc = sorted(clf.values())
p50 = float(np.percentile(allc, 50)); p70 = float(np.percentile(allc, 70))
print(f"clf10当日覆盖 {len(allc)} 只 | 中位 {p50:.3f} | P70 {p70:.3f} | 概率>0.5的 {sum(1 for x in allc if x>0.5)} 只 ({sum(1 for x in allc if x>0.5)/len(allc):.0%})")
print()
print(f"{'#':<3}{'代码':<9}{'名称':<10}{'行业':<12}{'reg10':>7}{'clf概率':>9}{'分位':>6}  clf意见")
for i, (code, name, ind, r) in enumerate(top, 1):
    s = clf.get(str(code))
    if s is None:
        print(f"{i:<4}{code:<9}{name:<10}{ind:<12}{r:>7.1f}    无clf分")
    else:
        q = sum(1 for x in allc if x <= s) / len(allc) * 100
        op = "同意涨" if s >= p70 else ("偏同意" if s >= p50 else "看跌")
        print(f"{i:<4}{code:<9}{name:<10}{ind:<12}{r:>7.1f}{s:>9.3f}{q:>5.0f}%  {op}")
# 共识票：10d top10 里 clf 也在自己 top10 的
clf_top10 = set(sorted(clf, key=lambda k: -clf[k])[:10])
both = [str(t[0]) for t in top if str(t[0]) in clf_top10]
print("\n双模型top10共识票:", both if both else "无")
