import os, sqlite3, json
import pandas as pd

base = os.path.expanduser('~/.hermes/stockdb')

# 1. 分钟库 date/time 列格式（min_feat_lib 口径依赖）
f = os.path.join(base, 'minutes/5min')
sample = [x for x in os.listdir(f) if x.endswith('.parquet')][:3]
for x in sample:
    d = pd.read_parquet(os.path.join(f, x))
    print(x, 'date dtype:', d['date'].dtype, '样例:', repr(d['date'].iloc[-1]),
          '| time 样例:', repr(d['time'].iloc[-1]))

# 2. mkt 前缀分布：存在 sz_ 开头但代码以 6 开头的？（f0 回落口径核查）
sz6 = [x for x in os.listdir(f) if x.startswith('sz_') and x[3] == '6']
sh_other = [x for x in os.listdir(f) if x.startswith('sh_') and x[3] not in '65']
print('sz_开头且代码6开头:', len(sz6), sz6[:5])
print('sh_开头且代码非6/5:', len(sh_other), sh_other[:5])

# 3. ic_shadow 列序（INSERT 无列名的位置依赖）
con = sqlite3.connect(os.path.join(base, 'signals.db'))
cols = [r[1] for r in con.execute("PRAGMA table_info(ic_shadow)")]
print('ic_shadow 列序:', cols)

# 4. shadow_v4e_scores 列数 vs INSERT VALUES(?,?,?)
cols4e = [r[1] for r in con.execute("PRAGMA table_info(shadow_v4e_scores)")]
print('shadow_v4e_scores 列:', cols4e)

# 5. v4e 模型特征数 vs 36 维拼接
import lightgbm as lgb
m = lgb.Booster(model_file=os.path.join(base, 'models/shadow_v4e/lgb_reg_v4e3.txt'))
print('v4e3 模型特征数:', m.num_feature(), '树数:', m.num_trees())
stats = json.loads(open(os.path.join(base, 'models/shadow_v4e/stats_v4e3.json')).read())
print('stats keys:', len(stats), list(stats.keys())[:3], '...')

# 6. 0904 v4e 分数分布 sanity（与 v4d 同日对比，看是否同一量纲）
a = pd.read_sql("SELECT code, score s4e FROM shadow_v4e_scores WHERE date='20260904'", con)
b = pd.read_sql("SELECT code, score s4d FROM shadow_v4d_scores WHERE date='20260904'", con)
c = a.merge(b, on='code')
print('重叠票:', len(c), '| v4e均值', round(c.s4e.mean(), 3), 'v4d均值', round(c.s4d.mean(), 3),
      '| 两两corr', round(c.s4e.corr(c.s4d), 3))
# NULL/inf 检查
print('v4e NULL:', a.s4e.isna().sum(), 'inf:', (~a.s4e.apply(lambda x: abs(x) < 1e6)).sum())