#!/usr/bin/env python3
"""补缺2026-06-04资金流"""
import requests, duckdb, time, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = '/Users/zantao/.hermes/stockdb/stock.db'

conn = duckdb.connect(DB, read_only=True)
codes = [r[0] for r in conn.execute('SELECT stock_code FROM stock_info').fetchall()]
conn.close()
print(f'Total stocks: {len(codes)}', flush=True)

def secid(code):
    return f'0.{code}' if code.startswith(('0','3','2')) else f'1.{code}'

def fetch_mf(code):
    try:
        url = 'https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get'
        params = {
            'secid': secid(code),
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55',
            'klt': '101', 'lmt': '3',
        }
        r = requests.get(url, params=params, timeout=10,
            headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
        data = r.json()
        klines = data.get('data',{}).get('klines',[])
        for k in klines:
            parts = k.split(',')
            if parts[0] == '2026-06-04':
                return (code, float(parts[1]))
    except:
        pass
    return None

local = duckdb.connect(DB)
inserted = 0
BATCH = 500

for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_mf, c): c for c in batch}
        for f in as_completed(futures):
            r = f.result()
            if r and r[1] != 0:
                code, mn = r
                try:
                    local.execute('INSERT OR REPLACE INTO money_flow (stock_code, date, main_net) VALUES (?,?,?)',
                        [code, '2026-06-04', mn])
                    inserted += 1
                except:
                    pass
    print(f'  {min(i+BATCH,len(codes))}/{len(codes)}, inserted={inserted}', flush=True)
    time.sleep(1.0)

local.close()
print(f'Done! Total inserted for 2026-06-04: {inserted}', flush=True)
