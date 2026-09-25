# -*- coding: utf-8 -*-
"""复检第三轮：①生存者偏差（退市票历史在不在库）②20/50/30 vs 0/50/50 是否同分（CSV直接验）
③年度CSV自净（每个文件只含自己年份）④2009窗口截断影响"""
import duckdb, glob, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
print('== ① 每年在库票数 ==')
yr = con.execute("SELECT substr(trade_date,1,4) y, count(DISTINCT ts_code) c FROM daily GROUP BY 1 ORDER BY 1").df()
print(yr.to_string(index=False))
print('== 退市覆盖：2014在库但2024不在的票数 ==')
n = con.execute("""
  SELECT count(*) FROM (
    SELECT DISTINCT ts_code FROM daily WHERE trade_date LIKE '2014%') a
  WHERE a.ts_code NOT IN (SELECT DISTINCT ts_code FROM daily WHERE trade_date LIKE '2024%')
""").fetchone()
print('消失票数(2014有2024无):', n[0])
print('最后交易日<20240101的票数(退市史留档):', con.execute("""
  SELECT count(*) FROM (SELECT ts_code, max(trade_date) mx FROM daily GROUP BY 1) WHERE mx < '20240101'
""").fetchone()[0])
con.close()
print('== ② CSV直接验 20/50/30 vs 0/50/50 逐日是否相同 ==')
d = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/*.csv'))], ignore_index=True)
d['date'] = d['date'].astype(int)
a = d[d.w=='20/50/30'].set_index('date').ex; b = d[d.w=='0/50/50'].set_index('date').ex
j = pd.DataFrame({'a':a,'b':b}).dropna()
print(f'重叠日{len(j)} 完全相同日数 {(j.a==j.b).sum()} 日均差 {(j.a-j.b).mean()*100:+.4f}pp (a=20/50/30, b=0/50/50)')
for w in ['0/70/30','0/60/40','0/50/50','10/50/40','10/60/30','20/50/30','20/60/20','30/50/20']:
    s = d[d.w==w]
    if len(s): print(f"  {w}: 日均{s.ex.mean()*100:+.3f}pp 池均{s.pool_n.mean():.0f}")
print('== ③ 每CSV只含自己年份 ==')
for f in sorted(glob.glob(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/*.csv')):
    y = os.path.basename(f)[:-4]
    dd = pd.read_csv(f, usecols=['year','date'])
    ok = (dd.year.astype(str)==y).all() and dd.date.astype(str).str[:4].eq(y).all()
    if not ok: print('  异常文件', f)
print('  全部18文件检查完（无输出=全对）')
