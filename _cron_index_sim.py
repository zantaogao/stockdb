"""只读模拟 update_index_daily：复现 start_date 计算 + 逐个指数调 API，不写库。"""
import json
import duckdb
import tushare as ts
from pathlib import Path
from datetime import datetime

BASE = Path.home() / '.hermes' / 'stockdb'
tdx = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
latest = tdx.execute("SELECT MAX(trade_date) FROM index_daily_raw").fetchone()[0]
tdx.close()
print(f'全表 MAX(trade_date) = {latest}')

start_date = str(int(latest) + 1)
end_date = datetime.now().strftime('%Y%m%d')
print(f'start_date = {start_date}, end_date = {end_date}')
if start_date > end_date:
    print('>>> 按脚本逻辑会打印"已是最新"并 return 0，不拉任何数据')
else:
    print('>>> 会进入拉取循环')

cfg = json.load(open(str(BASE / 'config.json')))
ts.set_token(cfg.get('tushare_token', ''))
pro = ts.pro_api()

idx_codes = ['000001.SH', '000300.SH', '000016.SH', '000688.SH',
             '000905.SH', '399001.SZ', '399006.SZ', '399852.SZ', '899050.BJ']
print()
print('=== 逐指数 API 返回（用脚本同样的 start/end）===')
for code in idx_codes:
    try:
        df = pro.index_daily(ts_code=code, start_date=start_date, end_date=end_date)
        if df is not None and len(df) > 0:
            print(f'{code}: {len(df)} 条, 日期 {df["trade_date"].min()}~{df["trade_date"].max()}')
        else:
            print(f'{code}: 空')
    except Exception as e:
        print(f'{code}: 异常 {str(e)[:100]}')

# 再测：用 7/25 起点（如果脚本用对起点应该拉到什么）
print()
print('=== 对照：start=20260725 时 000001.SH 应返回 ===')
df = pro.index_daily(ts_code='000001.SH', start_date='20260725', end_date=end_date)
print(df[['trade_date', 'close']].to_string(index=False) if df is not None and len(df) else '空')
