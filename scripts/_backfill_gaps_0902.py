"""2026-09-02 一次性补齐: tdx_intraday_feat 缺的 20260812/13/14/17
从 tdx_archive.db min1_archive 复用 tdx_intraday_agg.agg_day（口径零漂移）
"""
import sys, sqlite3, duckdb
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
from tdx_intraday_agg import agg_day

BASE = '/Users/zantao/.hermes/stockdb'
arch = duckdb.connect(f'{BASE}/tdx_archive.db', read_only=True)
sig = sqlite3.connect(f'{BASE}/signals.db')
GAPS = [20260812, 20260813, 20260814, 20260817]

for d in GAPS:
    df = arch.execute(f"""
        SELECT date, code AS stock, market, tm,
               "open" AS open, high, low, "close" AS close, volume AS vol
        FROM min1_archive WHERE date={d} AND "close" > 0
        ORDER BY code, tm""").df()
    rows = []
    for _, g in df.groupby('stock', sort=False):
        r = agg_day(g.reset_index(drop=True))
        if r:
            r['code'] = _
            rows.append(r)
    sig.execute("DELETE FROM tdx_intraday_feat WHERE date=?", (d,))
    sig.executemany(
        "INSERT OR REPLACE INTO tdx_intraday_feat "
        "(date,code,market,n_bars,open30_ret,tail30_ret,vwap_dev,rv_1m,amp_intra,vol_dist_am,vol_dist_tail,tail5_ret,last_vol_share) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r['date'], r['code'], r.get('market', ''), r['n_bars'], r['open30_ret'], r['tail30_ret'],
          r['vwap_dev'], r['rv_1m'], r['amp_intra'], r['vol_dist_am'], r['vol_dist_tail'],
          r['tail5_ret'], r['last_vol_share']) for r in rows])
    sig.commit()
    print(f"{d}: {len(rows)} 行")

chk = sig.execute("SELECT COUNT(*), SUM(tail5_ret IS NULL) FROM tdx_intraday_feat").fetchone()
print("全表行数/NULL:", chk)
sig.close(); arch.close()