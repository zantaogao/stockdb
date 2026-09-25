"""验证 income 接口 ann_date 全市场过滤"""
import tushare as ts
from datetime import datetime

pro = ts.pro_api()
today = datetime.now().strftime('%Y%m%d')
for api_name, fn in [('income', pro.income)]:
    try:
        df = fn(ann_date=today, fields='ts_code,end_date')
        n = len(df) if df is not None else 0
        print(f'{api_name}(ann_date={today}): {n} 家公告')
        if n > 0:
            print('  示例:', df.head(3).to_dict('records'))
    except Exception as e:
        print(f'{api_name}: 失败 {str(e)[:100]}')
# 也试近3天（覆盖周末公告）
for d in ['20260807', '20260810']:
    try:
        df = pro.income(ann_date=d, fields='ts_code,end_date')
        print(f'income(ann_date={d}): {len(df) if df is not None else 0} 家')
    except Exception as e:
        print(f'income(ann_date={d}): 失败 {str(e)[:80]}')
