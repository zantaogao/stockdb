#!/usr/bin/env python3
# 补充取数：指数近6日+宽度+风格+板块10日持续性+关键票日线（只读）
import duckdb, sqlite3, os, statistics, collections
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
TU = duckdb.connect('tushare.db', read_only=True)
SG = sqlite3.connect('file:signals.db?mode=ro', uri=True)

print('===== indexes last 6d =====')
for ts, nm in [('000001.SH','上证'), ('000852.SH','中证1000'), ('000016.SH','上证50'), ('399001.SZ','深证成')]:
    rows = TU.execute("SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6", [ts]).fetchall()
    print(nm, list(reversed(rows)))

print('===== market amount & breadth last 6d =====')
rows = TU.execute("""
SELECT trade_date, SUM(amount), COUNT(*) FROM daily WHERE trade_date >= '20260908' GROUP BY 1 ORDER BY 1
""").fetchall()
for d, amt, n in rows:
    up = TU.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg>0", [d]).fetchone()[0]
    dn = TU.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg<0", [d]).fetchone()[0]
    print(d, 'amt(亿)=%.0f' % (amt/1e5 if amt and amt>1e7 else amt/1e5), 'up', up, 'dn', dn, 'up%%=%.0f' % (up/(up+dn)*100))

print('===== ic_daily by-model last 10 =====')
cols = [r[1] for r in SG.execute("PRAGMA table_info(ic_daily)").fetchall()]
print('cols:', cols)
for r in SG.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall():
    print(r)

print('===== sector 10d persistence (daily x stock_basic industry) =====')
days = [r[0] for r in TU.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260901' ORDER BY 1 DESC LIMIT 10").fetchall()]
days = sorted(days)
print('days:', days)
sec = collections.defaultdict(dict)
for d, iname, chg in TU.execute(f"""SELECT d.trade_date, b.industry, AVG(d.pct_chg) FROM daily d
JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date >= '{days[0]}' AND b.industry IS NOT NULL AND b.industry != ''
GROUP BY 1,2""").fetchall():
    sec[iname][d] = round(chg, 2)
focus = ['种植业','房产服务','机械基件','黄金','铜','出版业','农药化肥','家居用品','汽车配件','软件服务','专用机械','纺织','化学制药','生物制药']
for d in days:
    rank = sorted(sec.items(), key=lambda kv: -kv[1].get(d, -99))
    pos = {k: i+1 for i, (k, v) in enumerate(rank)}
    line = []
    for f in focus:
        if f in pos:
            line.append(f"{f}:{sec[f].get(d,0):+.1f}(#{pos[f]})")
    print(d, ' '.join(line))

print('===== sector 5d cumulative ranking (last5d) =====')
last5 = days[-5:]
cum = sorted(((sum(sec[k].get(d,0) for d in last5), k) for k in sec), reverse=True)
print('TOP:', [(k, round(s,1)) for s, k in cum[:12]])
print('BOT:', [(k, round(s,1)) for s, k in cum[-12:]])

print('===== top/bottom sector daily ranks history (consecutive strength) =====')
allrank = {}
for d in days:
    rank = sorted(sec.items(), key=lambda kv: -kv[1].get(d, -99))
    allrank[d] = {k: i+1 for i, (k, v) in enumerate(rank)}
nsec = len(sec)
for s, k in cum[:12] + cum[-12:]:
    print(k, '5d=%.1f' % s, 'rankhist', [allrank[d].get(k) for d in days], '/n=%d' % nsec)
