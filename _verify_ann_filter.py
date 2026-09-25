"""验证 tushare 财报接口 ann_date 过滤（判断今天是否有新公告）"""
import tushare as ts
from datetime import datetime

pro = ts.pro_api()
today = datetime.now().strftime('%Y%m%d')
print(f'今天: {today}')

for api_name, fn in [('balancesheet', pro.balancesheet), ('cashflow', pro.cashflow)]:
    try:
        df = fn(ann_date=today, fields='ts_code,end_date')
        n = len(df) if df is not None else 0
        print(f'{api_name}(ann_date={today}): {n} 家公告')
        if n > 0:
            print('  示例:', df.head(3).to_dict('records'))
    except Exception as e:
        print(f'{api_name}: 失败 {str(e)[:100]}')
