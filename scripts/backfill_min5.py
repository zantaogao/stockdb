#!/usr/bin/env python3
# baostock 5分钟线全市场回填 → parquet/分钟库
# 用法: python3 backfill_min5.py [--workers 8] [--limit N]
# 断点续传: 已存在 parquet 的股票自动跳过; 失败记入 failed.txt
# 口径: 不复权原始价(adjustflag=3) — 涨跌停判断必须用真实价; 复权收益回测时再算
import os, sys, time, argparse, signal
import pandas as pd
import baostock as bs

BASE = os.path.expanduser('~/.hermes/stockdb/minutes/5min')
FAILED = os.path.expanduser('~/.hermes/stockdb/minutes/failed.txt')
START, END = '2025-04-08', '2026-09-04'
FIELDS = 'date,time,code,open,high,low,close,volume,amount'  # 分钟线不支持turn/pctChg
PER_STOCK_TIMEOUT = 120  # 单票取数上限秒数，超时按失败重试（防 baostock socket 挂死）

class _Timeout(Exception):
    pass

def _on_alarm(signum, frame):
    raise _Timeout('per-stock timeout')

signal.signal(signal.SIGALRM, _on_alarm)

_logged_in = False
def login():
    global _logged_in
    if not _logged_in:
        lg = bs.login()
        assert lg.error_code == '0', lg.error_msg
        _logged_in = True

def fetch_one(code):
    """code 形如 sh.600000"""
    out = os.path.join(BASE, code.replace('.', '_') + '.parquet')
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return (code, 'skip', 0)
    for attempt in range(3):
        try:
            signal.alarm(PER_STOCK_TIMEOUT)
            login()
            rs = bs.query_history_k_data_plus(
                code, FIELDS, start_date=START, end_date=END,
                frequency='5', adjustflag='3')
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                # baostock 限流时表现为 error_code=0 但空数据 → 按失败处理，可续传
                raise RuntimeError('empty result (likely rate-limited)')
            signal.alarm(0)
            df = pd.DataFrame(rows, columns=FIELDS.split(','))
            for c in ['open','high','low','close','volume','amount']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            df.to_parquet(out, compression='zstd')
            return (code, 'ok', len(df))
        except Exception as e:
            signal.alarm(0)
            global _logged_in
            _logged_in = False  # 会话可能断了，重登
            try:
                bs.logout()
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
            err = str(e)[:80]
    with open(FAILED, 'a') as f:
        f.write(f'{code}\t{err}\n')
    return (code, 'fail', 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    os.makedirs(BASE, exist_ok=True)

    # 股票清单: tushare.db 最近有日线的全部股票
    import duckdb
    d = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
    codes = [r[0] for r in d.execute(
        "SELECT DISTINCT ts_code FROM daily WHERE trade_date>='20250408' ORDER BY ts_code").fetchall()]
    d.close()
    todo = [('sh.' if c.endswith('.SH') else 'sz.') + c[:6] for c in codes]  # 000001.SZ -> sz.000001
    if args.limit:
        todo = todo[:args.limit]
    print(f'total {len(codes)}, to-fetch {len(todo)}, workers {args.workers}', flush=True)

    from multiprocessing import Pool
    t0 = time.time()
    done = ok = fail = skip = 0
    with Pool(args.workers) as p:
        for code, status, n in p.imap_unordered(fetch_one, todo, chunksize=4):
            done += 1
            ok += status == 'ok'; fail += status == 'fail'; skip += status == 'skip'
            if done % 100 == 0:
                el = time.time() - t0
                eta = el / done * (len(todo) - done) / 60
                print(f'[{done}/{len(todo)}] ok={ok} fail={fail} skip={skip} '
                      f'elapsed={el/60:.1f}min eta={eta:.0f}min', flush=True)
    print(f'DONE ok={ok} fail={fail} skip={skip} in {(time.time()-t0)/60:.1f}min', flush=True)

if __name__ == '__main__':
    main()