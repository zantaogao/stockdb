# 10d v6 训练: 新口径样本 samples_10d_v6.parquet (31维含新ex), 参数同v3/v5
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 复用0926训练脚本的train_one, 只换样本与输出名
import _cron_retrain_train_pc_0926 as T
T.train_one('10d_v6', 'samples_10d_v6.parquet', 'y10', 31,
            'lgb_reg_10d_v6.txt', 'v10_v6_stats.json', 'daily_ic_10d_v6.csv',
            dict(T.params, _max_rounds=2000, _es=50))
print('V6_DONE', flush=True)
