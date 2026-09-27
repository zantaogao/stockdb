# 生成 PC 侧重训脚本 v6b: 0926训练脚本 + 10d_v6 输出名替换(参数不动)
src=open('scripts/_cron_retrain_train_pc_0926.py',encoding='utf-8').read()
old="    train_one('10d_v5', 'samples_10d.parquet', 'y10', 31, 'lgb_reg_10d_v5.txt', 'v10_v5_stats.json', 'daily_ic_10d_v5.csv', dict(params, _max_rounds=2000, _es=50))"
new="    train_one('10d_v6', 'samples_10d_v6.parquet', 'y10', 31, 'lgb_reg_10d_v6.txt', 'v10_v6_stats.json', 'daily_ic_10d_v6.csv', dict(params, _max_rounds=2000, _es=50))"
assert old in src, 'old main段未找到'
out=src.replace(old,new).replace("print('ALL_DONE', flush=True)","print('V6_DONE', flush=True)")
open('scripts/_cron_retrain_v6_rerun_pc.py','w',encoding='utf-8').write(out)
print('written', len(out))
