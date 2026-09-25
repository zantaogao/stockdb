#!/usr/bin/env python3
"""Debug Sina stock price fetching"""
import json, urllib.request

SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn'}

def sina_code(code):
    if code == '000001': return 'sh000001'
    if code.startswith(('6', '68', '9')): return f'sh{code}'
    return f'sz{code}'

codes = ['688766', '300475', '603706', '603697', '603156', '002832', '002283', '603726', '603061']
sina_codes = [sina_code(c) for c in codes]

try:
    batch = ','.join(sina_codes)
    url = f'https://hq.sinajs.cn/list={batch}'
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    resp = urllib.request.urlopen(req, timeout=10)
    text = resp.read().decode('gbk')
    
    results = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or 'hq_str_' not in line:
            continue
        try:
            var_part = line.split('hq_str_')[1].split('=')[0]
            std_code = var_part[2:] if len(var_part) > 2 else var_part
            data_part = line.split('"')[1] if '"' in line else ''
            fields = data_part.split(',')
            results[std_code] = {
                'name': fields[0],
                'price': fields[3],
                'prev_close': fields[2],
            }
        except Exception as e:
            pass
    
    print(f"Got {len(results)} results from Sina")
    for k, v in list(results.items())[:3]:
        print(f"  {k}: {v['name']} price={v['price']} prev_close={v['prev_close']}")
    
    # Also test indices
    idx_url = 'https://hq.sinajs.cn/list=sh000001,sz399001,sz399006'
    req2 = urllib.request.Request(idx_url, headers=SINA_HEADERS)
    resp2 = urllib.request.urlopen(req2, timeout=10)
    text2 = resp2.read().decode('gbk')
    
    for line in text2.split('\n'):
        line = line.strip()
        if 'hq_str_' in line:
            var_part = line.split('hq_str_')[1].split('=')[0]
            data_part = line.split('"')[1]
            fields = data_part.split(',')
            print(f"  INDEX {var_part}: price={fields[3]}, prev_close={fields[2]}, name={fields[0]}")
            
except Exception as e:
    print(f"ERROR: {e}")
