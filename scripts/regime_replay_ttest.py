#!/usr/bin/env python3
"""regime_returns 显著性检验（09-13）：
A. 各环境 top10 等权日超额收益 t 检验（按日聚合，H0: 均值=0）
B. top10 vs tail40 配对差 t 检验（同环境同日的两边等权差）
C. 分年份单独看（样本小的标注）
"""
import duckdb, math, os
o = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/replay/regime_returns.duckdb'), read_only=True)

def ttest(vals):
    n = len(vals)
    if n < 3: return n, float('nan'), float('nan')
    m = sum(vals)/n
    sd = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
    t = m/(sd/math.sqrt(n)) if sd > 0 else float('nan')
    return n, m*100, t

daily = {}
for reg, d, rk, ex5 in o.execute("""
    SELECT regime, date, CASE WHEN rk<=10 THEN 'top' ELSE 'tail' END, ex5
    FROM replay_returns WHERE ex5 IS NOT NULL""").fetchall():
    daily.setdefault((reg, d, rk), []).append(ex5)

print("== A. top10 等权日超额（按日聚合，H0均值=0）")
print("环境     n天   日均ex5%  t值   |  同口径ex10见下")
order = ['crash','mild','flat','up']
for reg in order:
    v5 = [sum(vals)/len(vals) for (r,d,k),vals in daily.items() if r==reg and k=='top']
    n,m,t = ttest(v5)
    print(f"{reg:6s} {n:4d}  {m:+7.3f}  {t:+6.2f}")

d10 = o.execute("""
  SELECT regime, date, AVG(ex10) FROM replay_returns WHERE rk<=10 GROUP BY 1,2""").fetchall()
by = {}
for reg, d, x in d10: by.setdefault(reg, []).append(x)
print("\n== A2. top10 ex10 日均")
for reg in order:
    n,m,t = ttest(by.get(reg,[]))
    print(f"{reg:6s} {n:4d}  {m:+7.3f}  {t:+6.2f}")

print("\n== B. top10 vs tail40 配对差（日等权差，H0差=0）ex5")
pair = {}
for (reg,d,k),vals in daily.items():
    pair.setdefault((reg,d),{})[k] = sum(vals)/len(vals)
bt = {}
for (reg,d),kv in pair.items():
    if 'top' in kv and 'tail' in kv:
        bt.setdefault(reg,[]).append(kv['top']-kv['tail'])
for reg in order:
    n,m,t = ttest(bt.get(reg,[]))
    print(f"{reg:6s} {n:4d}  日均差{m:+7.3f}%  t={t:+6.2f}")

print("\n== C. 分年份×环境 top10 日均ex5 t 检验")
yr = {}
for y, reg, d, x in o.execute("SELECT yr, regime, date, AVG(ex5) FROM replay_returns WHERE rk<=10 AND ex5 IS NOT NULL GROUP BY 1,2,3").fetchall():
    yr.setdefault((y,reg),[]).append(x)
for (y,reg),v in sorted(yr.items()):
    n,m,t = ttest(v)
    flag = ' *' if abs(t)>=2 else ''
    print(f"{y} {reg:6s} n={n:4d}  日均{m:+6.3f}%  t={t:+5.2f}{flag}")
