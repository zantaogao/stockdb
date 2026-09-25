import glob, os, time

# Which 9 files changed in the fire window, and their encodings
lo = time.mktime(time.strptime('2026-09-01 21:50', '%Y-%m-%d %H:%M'))
hi = time.mktime(time.strptime('2026-09-01 23:00', '%Y-%m-%d %H:%M'))
for d in ['/Users/zantao/.hermes/scripts', '/Users/zantao/.hermes/stockdb',
          '/Users/zantao/.hermes/stockdb/scripts', '/Users/zantao/.hermes/stockdb/logs',
          '/Users/zantao/.hermes/stockdb/agents', '/Users/zantao/.hermes/stockdb/core']:
    for f in glob.glob(d + '/*'):
        if os.path.isfile(f) and lo <= os.path.getmtime(f) <= hi:
            b = open(f, 'rb').read(80)
            try:
                b.decode('utf-8')
                enc = 'utf8'
            except UnicodeDecodeError as e:
                enc = f'NOT-utf8({e.start})'
            print(time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(f))), os.path.basename(f), enc)