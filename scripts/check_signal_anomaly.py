#!/usr/bin/env python3
"""检查 signal_history 异常：7/29 vs 7/30 是否相同；8/3 reg40 骤降"""
import sqlite3

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')

# 1. 7/29 vs 7/30 逐行对比
print('=== 1. 7/29 vs 7/30 相同性检查 ===')
s29 = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT stock_code, reg10, reg20, reg40 FROM signal_history WHERE REPLACE(date,'-','')='20260729'")}
s30 = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT stock_code, reg10, reg20, reg40 FROM signal_history WHERE REPLACE(date,'-','')='20260730'")}
common = set(s29) & set(s30)
same = sum(1 for k in common if s29[k] == s30[k])
print(f'  共有 {len(common)} 只, 三模型分完全相同: {same} 只 ({same/len(common)*100:.0f}%)')

# 2. 8/3 reg40 分布 vs 备份库(17:30 旧扫描)
print('\n=== 2. 8/3 reg40 分布对比 ===')
for label, db in [('新库(重跑后)', '/Users/zantao/.hermes/stockdb/state.db'),
                  ('备份(17:30旧权重)', '/tmp/state.db.bak.20260803_235044_pre_rescan')]:
    cc = sqlite3.connect(db)
    r = cc.execute("SELECT ROUND(AVG(reg40),2), MIN(reg40), MAX(reg40) FROM signal_history WHERE REPLACE(date,'-','')='20260803'").fetchone()
    vals = sorted(x[0] for x in cc.execute("SELECT reg40 FROM signal_history WHERE REPLACE(date,'-','')='20260803'").fetchall())
    med = vals[len(vals)//2] if vals else 0
    print(f'  {label}: reg40 均值={r[0]} 范围=[{r[1]}, {r[2]}] 中位={med:.2f}')
    cc.close()

# 3. 7/31 vs 8/3 reg40 分布（正常 vs 异常）
print('\n=== 3. 7/31 vs 8/3 reg40 分桶分布 ===')
for day in ['20260731', '20260803']:
    rows = c.execute(f"""SELECT CASE WHEN reg40 < -5 THEN '<-5' WHEN reg40 < 0 THEN '-5~0' WHEN reg40 < 5 THEN '0~5' WHEN reg40 < 10 THEN '5~10' ELSE '>=10' END, COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='{day}' GROUP BY 1 ORDER BY 1""").fetchall()
    print(f'  {day}: {dict(rows)}')
