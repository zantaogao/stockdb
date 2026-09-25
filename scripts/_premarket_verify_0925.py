"""Step 2.5: pull 10-20d price history for holdings & top-10 list stocks.
Read-only from tushare.db (daily) and ledger.db (holdings)."""
import duckdb
import sqlite3
from collections import defaultdict

# ---------- holdings ----------
c = sqlite3.connect('ledger.db')
c.row_factory = sqlite3.Row
rows = c.execute("SELECT code, name, shares, avg_cost, latest_price from holdings").fetchall()
print("=== HOLDINGS (ledger.db) ===")
for r in rows:
    print(f"  {r['code']} {r['name']:10s}  shares={r['shares']} cost={r['avg_cost']} price={r['latest_price']}")
print()

# ---------- top-10 lists from draft ----------
top10_codes = [
    ('苏利股份','603585'), ('和泰机电','001225'), ('华图山鼎','300492'),
    ('圣诺生物','688117'), ('迪威尔','688377'), ('优优绿能','301590'),
    ('华绿生物','300970'), ('诚意药业','603811'), ('中兰环保','300854'),
    ('宏盛股份','603090'),
    ('广济药业','000952'), ('保利发展','600048'), ('延江股份','300658'),
    ('广宇集团','002133'), ('筑博设计','300564'), ('慧辰股份','688500'),
    ('圣达生物','603079'), ('东方电气','600875'), ('信维通信','300136'),
    ('美格智能','002881'),
    ('万邦达','300055'), ('冰川网络','300533'), ('三棵树','603737'),
    ('新华百货','600785'), ('飞沃科技','301232'), ('京能置业','600791'),
    ('富瑞特装','300228'), ('熊猫乳品','300898'),
    ('百合花','603823'), ('科达制造','600499'), ('芒果超媒','300413'),
    ('荣丰控股','000668'), ('读者传媒','603999'), ('瑞达期货','002961'),
    ('楚天龙','003040'),
]

# ---------- daily history from tushare.db ----------
db = duckdb.connect('tushare.db', read_only=True)
max_td = db.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print(f"latest trade_date: {max_td}")

# build per-stock 20d close history
all_closes = db.execute("""
    SELECT ts_code, trade_date, close
    FROM daily
    WHERE trade_date IN (
        SELECT trade_date FROM daily ORDER BY trade_date DESC LIMIT 20
    )
    ORDER BY ts_code, trade_date
""").fetchall()

hist_map = defaultdict(list)
for ts_code, td, close in all_closes:
    bare = ts_code.split('.')[0]
    hist_map[bare].append(close)

# dump raw data to a file for cross-check
with open('/Users/zantao/.hermes/stockdb/analysis/_verify_0925.txt', 'w') as fh:
    fh.write("=== 走势统计（近20日）===\n")
    fh.write("  code         name       5d%  10d% 20d%  距20d高%  连涨日  近3d%\n")
    for name, code in top10_codes:
        h = hist_map.get(code, [])
        if len(h) < 6:
            fh.write(f"  {code} {name:10s}  数据不足({len(h)}天)\n")
            continue
        w5, w10, w20, dist_hi, streak, w3 = stats(h)
        f = lambda x: f"{x:+.2f}%" if x is not None else "   -  "
        fh.write(f"  {code} {name:10s}  5d {f(w5)} 10d {f(w10)} 20d {f(w20)} 距20d高 {f(dist_hi)} 连涨{streak}日 近3d {f(w3)}\n")

    fh.write("\n=== 持仓 近20日走势 ===\n")
    for r in rows:
        code = r['code']
        h = hist_map.get(code, [])
        if len(h) < 6:
            fh.write(f"  {code} {r['name']:10s}  数据不足({len(h)}天)\n")
            continue
        w5, w10, w20, dist_hi, streak, w3 = stats(h)
        f = lambda x: f"{x:+.2f}%" if x is not None else "   -  "
        fh.write(f"  {code} {r['name']:10s}  5d {f(w5)} 10d {f(w10)} 20d {f(w20)} 距20d高 {f(dist_hi)} 连涨{streak}日 近3d {f(w3)}\n")

# also dump the raw close series for verification
with open('/Users/zantao/.hermes/stockdb/analysis/_verify_0925_closes.txt', 'w') as fh:
    for code in sorted(hist_map.keys()):
        closes = hist_map[code]
        fh.write(f"{code}: {len(closes)}days last5={closes[-5:]} last10={closes[-10:]} max20={max(closes)}\n")
def stats(closes):
    n = len(closes)
    def window(k):
        if n < k+1: return None
        return (closes[-1]/closes[-k-1] - 1) * 100
    w5 = window(5); w10 = window(10); w20 = window(20)
    hi20 = max(closes)
    dist_hi = (closes[-1]/hi20 - 1) * 100
    up_streak = 0
    for i in range(n-1, 0, -1):
        if closes[i] > closes[i-1]: up_streak += 1
        else: break
    w3 = (closes[-1]/closes[-4] - 1) * 100 if n >= 4 else None
    return w5, w10, w20, dist_hi, up_streak, w3

print("  code         name       5d%  10d% 20d%  距20d高%  连涨日  近3d%")
for name, code in top10_codes:
    h = hist_map.get(code, [])
    if len(h) < 6:
        print(f"  {code} {name:10s}  数据不足({len(h)}天)")
        continue
    w5, w10, w20, dist_hi, streak, w3 = stats(h)
    f = lambda x: f"{x:+.2f}%" if x is not None else "   -  "
    print(f"  {code} {name:10s}  5d {f(w5)} 10d {f(w10)} 20d {f(w20)} 距20d高 {f(dist_hi)} 连涨{streak}日 近3d {f(w3)}")

print()
print("=== 持仓 vs 榜内票 交叉 ===")
hold_codes = {r['code'] for r in rows}
top10_codeset = {c2 for _, c2 in top10_codes}
cross = hold_codes & top10_codeset
print(f"  持仓命中top10榜: {cross if cross else '无'}")

print("\n=== 持仓 近20日走势 ===")
for r in rows:
    code = r['code']
    h = hist_map.get(code, [])
    if len(h) < 6:
        print(f"  {code} {r['name']:10s}  数据不足({len(h)}天)")
        continue
    w5, w10, w20, dist_hi, streak, w3 = stats(h)
    f = lambda x: f"{x:+.2f}%" if x is not None else "   -  "
    print(f"  {code} {r['name']:10s}  5d {f(w5)} 10d {f(w10)} 20d {f(w20)} 距20d高 {f(dist_hi)} 连涨{streak}日 近3d {f(w3)}")
