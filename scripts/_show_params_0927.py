# 看三链训练脚本的模型参数(决定2019样本喂哪些配置)
import re
for f, tag in [('scripts/_cron_retrain_train_pc_0926.py','0926三链'),
               ('scripts/_cron_retrain_40d_v7_0926.py','40d_v7'),
               ('scripts/_cron_retrain_v6_c1_pc.py','v6c1')]:
    src = open(f).read()
    print(f'===== {tag} {f}')
    for line in src.splitlines():
        s = line.strip()
        if 'params' in s and ('=' in s or 'update' in s) and not s.startswith('#'):
            print('  ', s[:200])
    # train_one 调用行
    for line in src.splitlines():
        if 'train_one(' in line and not line.strip().startswith('def'):
            print('  CALL:', line.strip()[:220])
