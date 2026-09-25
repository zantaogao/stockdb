"""只读测试：验证 tushare API 能否拉到 000001.SH 7/25 之后的数据。不改任何库。"""
import json
import tushare as ts
from pathlib import Path

CONFIG = str(Path.home() / '.hermes' / 'stockdb' / 'config.json')
cfg = json.load(open(CONFIG))
token = cfg.get('tushare_token', '')
print('token 存在:', bool(token) and token != 'YOUR_TOKEN')
ts.set_token(token)
pro = ts.pro_api()

for code in ['000001.SH', '899050.BJ']:
    try:
        df = pro.index_daily(ts_code=code, start_date='20260725', end_date='20260803')
        if df is not None and len(df) > 0:
            print(f'{code}: API 返回 {len(df)} 条')
            print(df[['ts_code', 'trade_date', 'close']].head(10).to_string(index=False))
        else:
            print(f'{code}: API 返回空')
    except Exception as e:
        print(f'{code}: API 异常 {str(e)[:150]}')
