# 盘前核验·0928：last=最近A股交易日收盘+盘后估值，5日窗末端接入盘后估值
import duckdb, sqlite3, requests, json
from collections import defaultdict

HDR = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}

hold = {}
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
for code, name, px in c.execute("SELECT code,name,latest_price FROM holdings WHERE status='hold'").fetchall():
    hold[code] = (name, px)

db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = list(hold.keys())
q = """SELECT ts_code, trade_date, close FROM daily
WHERE ts_code IN ({}) AND trade_date<='20260925' ORDER BY ts_code, trade_date""".format(
    ','.join(f"'{c}.SH'" if c.startswith('6') else f"'{c}.SZ'" for c in codes))
by = defaultdict(list)
for r in db.execute(q).fetchall():
    by[r[0].split('.')[0]].append((r[1], r[2]))

def sina_quote(code):
    pre = 'gb_' + {'301093':'hualan'}  # dummy
    return None

# hq 现价：先试新浪A股
lst = ','.join(('sh' if c.startswith('6') else 'sz') + c for c in codes)
live = {}
try:
    r = requests.get(f'https://hq.sinajs.cn/list={lst}', headers=HDR, timeout=15)
    r.encoding = 'gbk'
    for line in r.text.strip().split('\n'):
        try:
            key = line.split('hq_str_')[1].split('=')[0]
            p = line.split('"')[1].split(',')
            code = key[2:]
            prevclose, todayopen, nowpx = float(p[2]), float(p[1]), float(p[3])
            live[code] = (prevclose, todayopen, nowpx, p[30], p[31])
        except Exception:
            pass
except Exception as e:
    print('live fail', e)

print('code name | last_daily(0924) ledger_px(0927eval) | 5d%(至0924) 5d%(接eval) 3d% vs20dHigh% 连涨')
for code in codes:
    name, evpx = hold[code]
    rr = by.get(code, [])
    closes = [x[1] for x in rr]
    if len(closes) < 6:
        print(code, name, 'insufficient'); continue
    last = closes[-1]
    seq = closes + ([evpx] if evpx and evpx > 0 else [])
    c5 = (seq[-1] / seq[-6] - 1) * 100
    c5_raw = (last / closes[-6] - 1) * 100
    a3 = (seq[-1] / seq[-4] - 1) * 100
    win = seq[-20:] if len(seq) >= 20 else seq
    hi = max(win)
    dist = (seq[-1] / hi - 1) * 100
    up = 0
    srt = sorted(set(rr), key=lambda x: x[0])
    vals = [x[1] for x in srt] + ([evpx] if evpx else [])
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i-1]: up += 1
        else: break
    lv = live.get(code)
    lvx = f" | live prevclose {lv[0]} open {lv[1]} now {lv[2]}" if lv else ''
    print(f"{code} {name} | {last} {evpx} | 5d_raw {c5_raw:+.1f}% 5d_eval {c5:+.1f}% 3d {a3:+.1f}% vsHI {dist:+.1f}% 连涨{up}日{lvx}")
