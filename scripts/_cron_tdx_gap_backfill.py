#!/usr/bin/env python3
"""一次性回补 tdx 缺口（20260812~20260831 共14个交易日，服务器端1分钟线仍在）
流程: pytdx 全市场拉1分钟线(翻够页数覆盖到08-03) → 只保留缺口日
      → 归档 min1_archive（只 DELETE 缺口日，好日不动）→ agg_day 聚合写 tdx_intraday_feat（同口径）
用法: /usr/bin/python3 -B scripts/_cron_tdx_gap_backfill.py
"""
import sys, time, csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import duckdb, sqlite3
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pytdx.hq import TdxHq_API
from tdx_pytdx_pull import get_stock_list, bars_to_rows
from tdx_intraday_agg import agg_day

BASE = Path('/Users/zantao/.hermes/stockdb')
GAPS = [20260812, 20260813, 20260814, 20260817, 20260818, 20260819, 20260820,
        20260821, 20260824, 20260825, 20260826, 20260827, 20260828, 20260831]
GAPSET = set(GAPS)
SERVERS = [('218.75.126.9', 7709), ('115.238.90.165', 7709)]
CSV_OUT = Path('/tmp/tdx_gap_min1.csv')

def pull_gap(api, code, mkt):
    """翻页直到最老bar早于最早缺口日，只留缺口日内的bar"""
    rows = []
    start = 0
    for _ in range(9):                      # 9页×800=7200根≈30交易日，够到08-03前
        try:
            bars = api.get_security_bars(8, mkt, code, start, 800)
        except Exception:
            break
        if not bars:
            break
        for r in bars_to_rows(code, mkt, bars):
            if int(r[2][:8]) in GAPSET:
                rows.append(r)
        oldest = str(bars[0].get('datetime', '')).replace('-', '')[:8]
        if oldest.isdigit() and int(oldest) < min(GAPSET):
            break
        start += 800
    return rows

def worker(args):
    code, mkt = args
    api = TdxHq_API()
    for host, port in SERVERS:
        try:
            if api.connect(host, port, time_out=6):
                break
        except Exception:
            continue
    else:
        return code, None
    try:
        return code, pull_gap(api, code, mkt)
    finally:
        try:
            api.disconnect()
        except Exception:
            pass

def main():
    stocks = get_stock_list()
    print(f"股票数 {len(stocks)}，回补 {len(GAPS)} 个缺口日")
    t0 = time.time()
    all_rows = []
    nfail = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(worker, s): s for s in stocks}
        done = 0
        for fut in as_completed(futs):
            code, rows = fut.result()
            if rows is None:
                nfail += 1
            elif rows:
                all_rows.extend(rows)
            done += 1
            if done % 1000 == 0:
                print(f"  {done}/{len(stocks)}，已拉 {len(all_rows)} 行，{time.time()-t0:.0f}s", flush=True)
    print(f"拉取完成: {len(all_rows)} 行，失败 {nfail} 只，耗时 {time.time()-t0:.0f}s")
    if len(all_rows) < 100000:
        print("⚠️ 行数异常偏少，可能服务器已滚动掉缺口日，中止不写")
        sys.exit(1)

    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['code','market','datetime','open','high','low','close','amount','volume'])
        w.writerows(all_rows)
    print(f"✅ CSV: {CSV_OUT}")

    # 归档：只 DELETE 缺口日再 INSERT（好日不动）
    import pandas as pd
    df = pd.read_csv(CSV_OUT, dtype={'code': str})
    df['date'] = df['datetime'].str[:8].astype(int)
    df['tm'] = df['datetime'].str[9:11].astype(int) * 60 + df['datetime'].str[11:13].astype(int)
    df = df[['date','code','market','tm','open','high','low','close','volume']]
    arch = duckdb.connect(str(BASE / 'tdx_archive.db'))
    for d in GAPS:
        arch.execute("DELETE FROM min1_archive WHERE date=?", (d,))
    arch.execute("INSERT INTO min1_archive SELECT date, code, market, tm, open, high, low, close, volume FROM df")
    cov = arch.execute(f"SELECT date, COUNT(DISTINCT code) FROM min1_archive WHERE date IN ({','.join(map(str,GAPS))}) GROUP BY date ORDER BY date").fetchall()
    print("归档覆盖:", cov)
    arch.close()

    # 聚合：agg_day 同口径重建 tdx_intraday_feat（与 _backfill_gaps_0902.py 逐字一致）
    arch = duckdb.connect(str(BASE / 'tdx_archive.db'), read_only=True)
    sig = sqlite3.connect(str(BASE / 'signals.db'))
    for d in GAPS:
        gdf = arch.execute(f"""
            SELECT date, code AS stock, market, tm,
                   "open" AS open, high, low, "close" AS close, volume AS vol
            FROM min1_archive WHERE date={d} AND "close" > 0
            ORDER BY code, tm""").df()
        rows = []
        for _, g in gdf.groupby('stock', sort=False):
            r = agg_day(g.reset_index(drop=True))
            if r:
                r['code'] = _
                rows.append(r)
        sig.execute("DELETE FROM tdx_intraday_feat WHERE date=?", (d,))
        sig.executemany(
            "INSERT OR REPLACE INTO tdx_intraday_feat "
            "(date,code,market,n_bars,open30_ret,tail30_ret,vwap_dev,rv_1m,amp_intra,vol_dist_am,vol_dist_tail,tail5_ret,last_vol_share) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r['date'], r['code'], r.get('market',''), r['n_bars'], r['open30_ret'], r['tail30_ret'],
              r['vwap_dev'], r['rv_1m'], r['amp_intra'], r['vol_dist_am'], r['vol_dist_tail'],
              r['tail5_ret'], r['last_vol_share']) for r in rows])
        sig.commit()
        print(f"{d}: 特征 {len(rows)} 行")
    sig.close(); arch.close()
    print("TDX_GAP_BACKFILL_DONE")

if __name__ == '__main__':
    main()