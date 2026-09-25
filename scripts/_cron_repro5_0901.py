import sqlite3, glob, hashlib, os, time

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t in ['fusion_3f_signals', 'fusion_center_signals']:
    cols = [r[1] for r in sig.execute(f'PRAGMA table_info({t})')]
    print(t, 'cols:', cols[:6])

# Exact reproduction candidates: decode bytes 35-60 of the warning with GBK
b = open('/Users/zantao/.hermes/scripts/backfill_stk_factor.sh', 'rb').read()
line = [l for l in b.split(b'\n') if '失败' in l or b'\xe5\xa4\xb1\xe8\xb4\xa5' in l][0]
print('shell warning line bytes:', line)
# Try: utf8 bytes read with errors='ignore' — position shifts:
try:
    line.decode('utf-8', errors='strict')
    print('line decodes fine')
except UnicodeDecodeError as e:
    print('line decode err', e)
# GBK-decode the warning and re-encode:
gbk = line.decode('utf-8').encode('gbk')
print('gbk re-encode byte42:', hex(gbk[42]))