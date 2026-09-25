#!/usr/bin/env python3
"""核查 Sina 实时价是否新鲜：打印原始字段 + 与 DB 20260924 收盘对比"""
import sys
import urllib.request
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import duckdb

codes = ['688500', '300970', '300055', '001238', '300837', '000852']
INDEX = {'000852': 'sh000852'}
sina = ','.join(INDEX.get(c) or (f"sh{c}" if c.startswith(('6', '68', '9')) else f"sz{c}") for c in codes)
req = urllib.request.Request(f"https://hq.sinajs.cn/list={sina}",
                            headers={"Referer": "https://finance.sina.com.cn"})
raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk')
print('--- RAW ---')
for line in raw.strip().split('\n'):
    scode = line.split('hq_str_')[1].split('=')[0] if 'hq_str_' in line else '?'
    body = line.split('"')[1] if '"' in line else ''
    parts = body.split(',')
    if len(parts) > 5:
        print(f"{scode}: name={parts[0]} open={parts[1]} prev={parts[2]} now={parts[3]} high={parts[4]} low={parts[5]} date={parts[-3]} time={parts[-2]}")
    else:
        print(scode, 'EMPTY')

tdu = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
print('--- DB close 20260924 ---')
for c in ['688500', '300970', '300055', '001238', '300837']:
    ts = c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ')
    r = tdu.execute("SELECT trade_date, close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 2", (ts,)).fetchall()
    print(c, r)
tdu.close()
