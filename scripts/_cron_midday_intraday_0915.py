import sys, urllib.request
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import duckdb

codes = ['688636', '301557', '603202', '002454', '605598', '688093', '300658', '688186',
         '300986', '301110', '301093', '001332', '603966', '301237', '601615']
names = {'688636': '智明达', '301557': '常友科技', '603202': '天有为', '002454': '松芝股份',
         '605598': '上海港湾', '688093': '世华科技', '300658': '延江股份', '688186': '广大特材',
         '300986': '志特新材', '301110': '青木科技', '301093': '华兰股份', '001332': '锡装股份',
         '603966': '法兰泰克', '301237': '和顺科技', '601615': '明阳智能'}


def sc(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(sc(c) for c in codes),
                             headers={'Referer': 'https://finance.sina.com.cn'})
raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk', 'ignore')
q = {}
for line in raw.strip().split('\n'):
    if 'hq_str_' not in line or '=""' in line:
        continue
    code = line.split('hq_str_')[1].split('=')[0][2:]
    p = line.split('"')[1].split(',')
    if len(p) < 32:
        continue
    q[code] = {'open': float(p[1]), 'prev': float(p[2]), 'px': float(p[3]),
               'high': float(p[4]), 'low': float(p[5]), 'amt': float(p[9])}

con = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
hist = {}
for c in codes:
    ts = c + ('.SH' if c.startswith(('6', '9')) else '.SZ')
    r = con.execute("SELECT trade_date, open, high, low, close FROM daily WHERE ts_code=? AND trade_date>='20260908' ORDER BY trade_date", [ts]).fetchall()
    hist[c] = r
con.close()

print('%-9s %-6s %7s %7s %7s %7s %7s %7s   %s' % ('code', '名称', '昨收', '今开', '最高', '最低', '现价', '日内%', '近5日区间(低-高)'))
for c in codes:
    v = q.get(c)
    if not v:
        print(c, '无数据')
        continue
    h = hist[c]
    lo = min(x[3] for x in h)
    hi = max(x[2] for x in h)
    print('%-9s %-6s %7.2f %7.2f %7.2f %7.2f %7.2f %+7.2f   %.2f - %.2f  (昨收%.2f 昨开%.2f)' % (
        c, names[c], v['prev'], v['open'], v['high'], v['low'], v['px'],
        (v['px'] / v['prev'] - 1) * 100, lo, hi, h[-1][4], h[-1][1]))
print('\n昨日(20260914) 延江股份 开%.2f 低%.2f 收%.2f' % (hist['300658'][-1][1], hist['300658'][-1][3], hist['300658'][-1][4]))
