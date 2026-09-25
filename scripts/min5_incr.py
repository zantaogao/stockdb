#!/usr/bin/env python3
# baostock 5分钟线·夜间增量（v4e 影子链依赖，2026-09-06）
# 每票 parquet 末日期 < 目标日 → 只拉缺口区间追加；已覆盖 → skip。
# 失败容忍：单票失败记 minutes/failed_incr.txt，不中断；缺票当日 v4e 该票 f50-f53 为 NaN（LGBM 原生处理）。
# 用法: python3 min5_incr.py [--workers 8] [--date YYYY-MM-DD]（date 默认今天）
import os, sys, time, argparse, signal
import pandas as pd
import baostock as bs

BASE = os.path.expanduser('~/.hermes/stockdb/minutes/5min')
FAILED = os.path.expanduser('~/.hermes/stockdb/minutes/failed_incr.txt')
FIELDS = 'date,time,code,open,high,low,close,volume,amount'
PER_STOCK_TIMEOUT = 90

class _Timeout(Exception):
    pass

def _on_alarm(signum, frame):
    raise _Timeout('per-stock timeout')

signal.signal(signal.SIGALRM, _on_alarm)

def login():
    lg = bs.login()
    assert lg.error_code == '0', lg.error_msg

def fetch_one(args):
    code, end = args   # code 'sh.600000'; end 'YYYY-MM-DD'
    out = os.path.join(BASE, code.replace('.', '_') + '.parquet')
    if not (os.path.exists(out) and os.path.getsize(out) > 1000):
        return (code, 'nofile', 0)
    try:
        last = str(pd.read_parquet(out, columns=['date'])['date'].max())
    except Exception:
        return (code, 'corrupt', 0)
    if last >= end:
        return (code, 'skip', 0)
    start = (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    for attempt in range(3):
        try:
            signal.alarm(PER_STOCK_TIMEOUT)
            login()
            rs = bs.query_history_k_data_plus(
                code, FIELDS, start_date=start, end_date=end,
                frequency='5', adjustflag='3')
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
            signal.alarm(0)
            if not rows:
                return (code, 'nodata', 0)   # 停牌/未更新，非错误
            new = pd.DataFrame(rows, columns=FIELDS.split(','))
            for c in ['open','high','low','close','volume','amount']:
                new[c] = pd.to_numeric(new[c], errors='coerce')
            old = pd.read_parquet(out)
            combined = (pd.concat([old, new], ignore_index=True)
                        .drop_duplicates(subset=['time'], keep='last')
                        .sort_values('time'))
            combined.to_parquet(out, compression='zstd')
            return (code, 'ok', len(new))
        except Exception as e:
            signal.alarm(0)
            try:
                bs.logout()
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
            err = str(e)[:80]
    with open(FAILED, 'a') as f:
        f.write(f'{code}\t{end}\t{err}\n')
    return (code, 'fail', 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--date', default=time.strftime('%Y-%m-%d'))
    args = ap.parse_args()
    todo = [('sh.' if c.endswith('.SH') else 'sz.') + c[:6]
            for c in sorted(fn[3:9] for fn in os.listdir(BASE) if fn.endswith('.parquet'))]
    print(f'增量目标 {args.date}，票数 {len(todo)}, workers {args.workers}', flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    done = ok = fail = skip = nodata = 0
    with Pool(args.workers) as p:
        for code, status, n in p.imap_unordered(fetch_one, [(c, args.date) for c in todo], chunksize=4):
            done += 1
            ok += status == 'ok'; fail += status == 'fail'
            skip += status == 'skip'; nodata += status == 'nodata'
            if done % 500 == 0:
                el = time.time() - t0
                print(f'[{done}/{len(todo)}] ok={ok} fail={fail} skip={skip} nodata={nodata} '
                      f'elapsed={el/60:.1f}min', flush=True)
    el = time.time() - t0
    print(f'增量完成 ok={ok} fail={fail} skip={skip} nodata={nodata} 用时{el/60:.1f}min', flush=True)
    if fail > 200:
        print(f'MIN5_INCR_HIGH_FAIL {fail}', flush=True)
        sys.exit(1)

if __name__ == '__main__':
    main()