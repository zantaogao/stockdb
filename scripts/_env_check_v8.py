# v8 三链重训 环境核查（在 PC 上以 WSL root 跑，不训练只验环境）
import sys, json
print('python:', sys.version.split()[0], sys.executable)
try:
    import lightgbm as lgb
    print('lightgbm:', lgb.__version__)
except Exception as e:
    print('lightgbm FAIL:', repr(e)[:100])
try:
    import pandas as pd, numpy as np
    print('pandas:', pd.__version__, 'numpy:', np.__version__)
    df = pd.read_parquet('C:/Users/zantan/retrain_20260927/samples_10d.parquet', columns=['date','code','y10'])
    print('样本读取 OK:', len(df), '行', df.date.min(), '~', df.date.max())
except Exception as e:
    print('parquet FAIL:', repr(e)[:150])
