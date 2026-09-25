import sqlite3
import pandas as pd
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
old = pd.read_sql("SELECT code, score s_old FROM _tmp_v4e_old WHERE date='20260904'", con)
new = pd.read_sql("SELECT code, score s_new FROM shadow_v4e_scores WHERE date='20260904'", con)
c = old.merge(new, on='code')
print('重叠票:', len(c))
print('旧分数 corr(新):', round(c.s_old.corr(c.s_new), 3))
print('旧分数 std:', round(c.s_old.std(), 4), '新分数 std:', round(c.s_new.std(), 4))
# 与 v4d 的相关性（修复后应该更合理）
d = pd.read_sql("SELECT code, score s4d FROM shadow_v4d_scores WHERE date='20260904'", con)
c = c.merge(d, on='code')
print('corr(v4e新, v4d):', round(c.s_new.corr(c.s4d), 3), ' corr(v4e旧, v4d):', round(c.s_old.corr(c.s4d), 3))
# 排序重合度 top50
t_old = set(c.nlargest(50, 's_old')['code']); t_new = set(c.nlargest(50, 's_new')['code'])
print('top50 重合:', len(t_old & t_new))
con.execute("DROP TABLE _tmp_v4e_old"); con.commit()
print('临时表已清理')