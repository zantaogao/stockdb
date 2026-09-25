# Find candidate 0xbc-containing files modified around the 22:00 cron fire (22:00:19-22:55)
import glob, os, time, datetime

lo = time.mktime(datetime.datetime(2026, 9, 1, 21, 50).timetuple())
hi = time.mktime(datetime.datetime(2026, 9, 1, 23, 0).timetuple())
hits = []
for d in ['/Users/zantao/.hermes/scripts', '/Users/zantao/.hermes/stockdb',
          '/Users/zantao/.hermes/stockdb/scripts', '/Users/zantao/.hermes/stockdb/logs',
          '/Users/zantao/.hermes/stockdb/agents', '/Users/zantao/.hermes/stockdb/core']:
    for f in glob.glob(d + '/*'):
        if not os.path.isfile(f):
            continue
        mt = os.path.getmtime(f)
        if lo <= mt <= hi:
            b = open(f, 'rb').read(100)
            if len(b) > 42 and b[42] == 0xbc:
                try:
                    b.decode('utf-8')
                    ok = 'utf8-ok'
                except UnicodeDecodeError:
                    ok = 'BAD-UTF8-at-42'
                hits.append((time.strftime('%H:%M', time.localtime(mt)), f, ok))
for h in sorted(hits):
    print(h)
print('total modified in window (not just 0xbc):')
cnt = sum(1 for d in ['/Users/zantao/.hermes/scripts', '/Users/zantao/.hermes/stockdb',
                      '/Users/zantao/.hermes/stockdb/scripts', '/Users/zantao/.hermes/stockdb/logs',
                      '/Users/zantao/.hermes/stockdb/agents', '/Users/zantao/.hermes/stockdb/core']
          for f in glob.glob(d + '/*') if os.path.isfile(f) and lo <= os.path.getmtime(f) <= hi)
print(cnt)