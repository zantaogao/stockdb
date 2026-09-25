import sys, time, urllib.request
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import duckdb

con = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
maxd = con.execute('SELECT MAX(trade_date) FROM daily').fetchone()[0]
try:
    rows = con.execute("SELECT ts_code, name, industry FROM stock_basic WHERE list_status='L'").fetchall()
except Exception:
    rows = con.execute('SELECT ts_code, name, industry FROM stock_basic').fetchall()
info = {}
for ts, nm, ind in rows:
    c = str(ts).split('.')[0]
    if len(c) == 6 and c.isdigit():
        info[c] = (nm, ind)

mv = {}
try:
    for ts, cm in con.execute('SELECT ts_code, circ_mv FROM daily_basic WHERE trade_date=?', [maxd]).fetchall():
        mv[str(ts).split('.')[0]] = cm
except Exception as e:
    print('circ_mv err', e)
con.close()
print('股票池', len(info), ' 市值样本', len(mv), ' 最新交易日', maxd)


def sina_code(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


def fetch(chunk):
    sc = ','.join(sina_code(c) for c in chunk)
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + sc,
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk', 'ignore')
    out = {}
    for line in raw.strip().split('\n'):
        if 'hq_str_' not in line or '=""' in line:
            continue
        try:
            scode = line.split('hq_str_')[1].split('=')[0]
            parts = line.split('"')[1].split(',')
            if len(parts) < 10:
                continue
            c = scode[2:]
            px = float(parts[3] or 0)
            prev = float(parts[2] or 0)
            amt = float(parts[9] or 0)
            if px > 0 and prev > 0:
                out[c] = ((px / prev - 1) * 100, amt)
        except Exception:
            continue
    return out


codes = sorted(info)
quotes = {}
t0 = time.time()
for i in range(0, len(codes), 500):
    chunk = codes[i:i + 500]
    for a in range(2):
        try:
            quotes.update(fetch(chunk))
            break
        except Exception:
            time.sleep(0.3)
print('行情 %d 只 耗时 %.0fs' % (len(quotes), time.time() - t0))

# 行业聚合
agg = {}
for c, (chg, amt) in quotes.items():
    ind = (info[c][1] or '未知').strip()
    agg.setdefault(ind, []).append(chg)
res = []
for ind, lst in agg.items():
    if len(lst) < 8:
        continue
    lst = sorted(lst)
    med = lst[len(lst) // 2]
    up = sum(1 for x in lst if x > 0.05) / len(lst) * 100
    res.append((med, ind, len(lst), up))
res.sort(reverse=True)
print('\n=== 行业半日表现（中位涨幅，样本≥8只）===')
print('-- 前12强 --')
for med, ind, n, up in res[:12]:
    print('  %-12s 中位%+6.2f%%  涨占比%5.1f%%  n=%d' % (ind, med, up, n))
print('-- 后12弱 --')
for med, ind, n, up in res[-12:]:
    print('  %-12s 中位%+6.2f%%  涨占比%5.1f%%  n=%d' % (ind, med, up, n))

# 市值分层
buckets = []
for c, (chg, amt) in quotes.items():
    m = mv.get(c)
    if m:
        buckets.append((m, chg))
buckets.sort()
n = len(buckets)
print('\n=== 市值分层（circ_mv 万元，等分5档）===')
labs = ['最小20%', '小20%', '中20%', '大20%', '最大20%']
for i in range(5):
    seg = [x[1] for x in buckets[i * n // 5:(i + 1) * n // 5]]
    seg.sort()
    med = seg[len(seg) // 2]
    print('  %-7s 中位%+6.2f%%  涨占比%5.1f%%  n=%d  均市值%.0f亿' % (
        labs[i], med, sum(1 for x in seg if x > 0.05) / len(seg) * 100, len(seg),
        sum(buckets[i * n // 5:(i + 1) * n // 5][j][0] for j in range(len(seg))) / len(seg) / 1e4))

# 主账户持仓 + 策略账户相关票
watch = ['688636', '301557', '603202', '002454', '605598', '688093', '300658', '688186',
         '300986', '301110', '301093', '001332', '603966', '301237', '601615']
print('\n=== 主账户持仓半日 ===')
for c in watch:
    v = quotes.get(c)
    if v:
        print('  %s %-6s %+6.2f%%' % (c, info.get(c, ('', ''))[0][:5], v[0]))
