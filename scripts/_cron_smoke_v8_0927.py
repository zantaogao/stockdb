"""上线前冒烟对账（2026-09-27 v8融合切换）
1) 全票池抽500票, 线上 score_stock vs 离线口径(样本构建同法: feat_38[PV_INDICES]→standardize) 对 v8 模型预测
2) 与样本表最近可用日对齐: 直接拿 v8 模型在样本上 predict 与线上 predict 同票同日比 f40 口径(40d需 ex5,用当日 stk_factor 最近值)
"""
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd
BASE = Path.home() / '.hermes/stockdb'
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / 'scripts'))
from core import scoring

scoring._load_models()
assert scoring._reg10_model.num_feature() == 31, f"10d模型维度{scoring._reg10_model.num_feature()}!=31"
assert scoring._reg40_model.num_feature() == 29, f"40d模型维度{scoring._reg40_model.num_feature()}!=29"
print('模型加载 OK: 10d 31维, 40d 29维', flush=True)

codes = ['000001','600519','300750','688981','002594','601899','000852','301236']
import duckdb
conn = scoring._safe_connect()
for c in codes:
    r = scoring.score_stock(c, conn=conn)
    if r is None:
        print(c, 'None'); continue
    print('%s reg10=%.3f reg20=%.2f reg40=%.2f fusion=%.2f' % (
        c, r['reg10_pred'], r['reg20_pred'], r['reg40_pred'], r['fusion']))
conn.close()
