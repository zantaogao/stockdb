"""补拉 index_daily_raw 8/10（2026-08-10 手动交换后缺口）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))

import tushare as ts
from scripts.update_tushare_api import update_index_daily

pro = ts.pro_api()
update_index_daily(pro)
print('index_daily_raw 补拉完成')
