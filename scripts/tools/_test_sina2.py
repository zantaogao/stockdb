#!/usr/bin/env python3
"""Test Sina with 36 stock codes"""
import json, urllib.request

SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn'}

def sina_code(code):
    if code == '000001': return 'sh000001'
    if code.startswith(('6', '68', '9')): return f'sh{code}'
    return f'sz{code}'

# All stock codes
hold = ['688766', '300475', '603706', '603697', '603156', '002832', '002283', '603726', '603061']
watch = ['300723', '603045', '688111', '002768', '002039', '688525', '000506', '002275', '603929', '300751', '002149', '002565', '000547', '601127', '301269', '002241', '002460', '000426', '300342', '301550', '002342', '600988', '300085', '300870', '002738', '002837', '002709']

all_codes = [sina_code(c) for c in hold + watch]
print(f"Total stock codes: {len(all_codes)}")

try:
    batch = ','.join(all_codes)
    url = f'https://hq.sinajs.cn/list={batch}'
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
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
            if len(fields) >= 6:
                results[std_code] = {
                    'name': fields[0],
                    'price': float(fields[3]) if fields[3] else 0,
                    'prev_close': float(fields[2]) if fields[2] else 0,
                    'change_pct': round((float(fields[3]) - float(fields[2])) / float(fields[2]) * 100, 2) if float(fields[2]) > 0 else 0
                }
        except Exception as e:
            pass
    
    print(f"Parsed {len(results)} results")
    for k, v in list(results.items())[:5]:
        print(f"  {k}: {v['name']} price={v['price']} change={v['change_pct']}%")
except Exception as e:
    print(f"ERROR: {e}")
