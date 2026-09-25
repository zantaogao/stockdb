#!/usr/bin/env python3
# 5分钟线·夜间增量（TDX 源，2026-09-08 全面切换，替代 baostock 版 min5_incr.py）
# 数据源：PC(192.168.3.168) C:/Users/zanta/tdx_stock_data.db min5 表
#   （PC 侧 15:30 update_tdx_sina.py + 16:10 tdx_sync.sh 已保证当日数据到位）
# 拉取上界 = 昨天（T-1）：今晚拉 T-1 保证全天完整，今日缺口留明晚，杜绝半截数据。
# 去重口径：time 主键。--overwrite-dates 里的日期 TDX 行强制覆盖旧行
#   （一次性统一 9/7、9/8 两天 baostock 半截增量到 TDX 口径）。
# 范围：只更新 5min/ 已有 parquet 的票（v4e 口径），ETF/北交所扩容另行决策。
# 部署前提：本脚本以 /usr/bin/python3 -B 跑（有 duckdb+pandas），cron 里挂这条。
# 用法: /usr/bin/python3 -B scripts/min5_incr_tdx.py [--overwrite-dates 2026-09-07,2026-09-08]
import os, sys, subprocess, tempfile, time, argparse
import pandas as pd

BASE = os.path.expanduser('~/.hermes/stockdb/minutes/5min')
PC = 'zantan@192.168.3.168'
PC_PY = r'C:\Program Files\Python311\python.exe'

REMOTE_FETCH = """
import sqlite3, sys
c = sqlite3.connect(r'file:C:/Users/zanta/tdx_stock_data.db?mode=ro', uri=True)
start, end = sys.argv[1], sys.argv[2]
cur = c.execute(
    "SELECT market||'.'||code,datetime,open,high,low,close,volume,amount "
    "FROM min5 WHERE datetime>=? AND datetime<=? ORDER BY 1,2", (start, end + ' 24'))
out = sys.stdout
out.write('code,datetime,open,high,low,close,volume,amount\\n')
while True:
    rows = cur.fetchmany(20000)
    if not rows:
        break
    for r in rows:
        out.write(','.join(str(x) for x in r) + '\\n')
"""


def fetch_delta(start, end, csv_gz):
    """ssh PC python stdin传脚本，stdout 落本地文件。"""
    with open(csv_gz, 'w') as fout:
        r = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=10', PC,
             f'"{PC_PY}" - {start} {end}'],
            input=REMOTE_FETCH, stdout=fout,
            stderr=subprocess.PIPE, timeout=3600, text=True)
    if r.returncode != 0 or os.path.getsize(csv_gz) < 100:
        # text=True 时 stderr 已是 str（09-17 踩坑：subprocess 失败路径 .decode() 反吞真错）
        raise RuntimeError(f'ssh fetch rc={r.returncode} err={str(r.stderr)[-300:]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--overwrite-dates', default='',
                    help='逗号分隔 YYYY-MM-DD，这些日期 TDX 行覆盖旧行')
    ap.add_argument('--end', default='',
                    help='拉取上界 YYYY-MM-DD（默认 T-1；指定则拉到该日含当日）')
    args = ap.parse_args()
    ovr = {d.strip().replace('-', '') for d in args.overwrite_dates.split(',') if d.strip()}

    files = [f for f in os.listdir(BASE) if f.endswith('.parquet')]
    if not files:
        print('MIN5_TDX_FAIL 本地无 parquet'); sys.exit(1)

    tminus1 = (args.end.replace('-', '') if args.end
               else (pd.Timestamp.today() - pd.Timedelta(days=1)).strftime('%Y%m%d'))
    # 下界 = 各票最大日期的最小值（有票掉队则整体从最老掉队日重拉，合并幂等）
    import duckdb
    glob = os.path.join(BASE, '*.parquet')
    con = duckdb.connect()
    dmin_max = con.execute(
        f"SELECT MIN(date_max) FROM ("
        f"SELECT filename, max(replace(date,'-','')) date_max "
        f"FROM read_parquet('{glob}') GROUP BY filename)").fetchone()[0]
    if dmin_max >= tminus1:
        print(f'MIN5_TDX_SKIP 全部票已覆盖到 T-1({tminus1})')
        return
    start, end = dmin_max, tminus1

    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix='min5_tdx_')
    csv_gz = os.path.join(tmp, 'delta.csv')
    fetch_delta(start, end, csv_gz)

    delta = pd.read_csv(csv_gz)
    delta['date'] = delta['datetime'].str[:8]
    delta['time'] = delta['date'] + delta['datetime'].str[9:13] + '00000'
    for c in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        delta[c] = pd.to_numeric(delta[c], errors='coerce')
    # 时间格式对齐本地库：本地 date='YYYY-MM-DD' time='YYYYMMDDHHMMSS000'
    delta['date'] = delta['date'].str.replace(r'(\d{4})(\d{2})(\d{2})', r'\1-\2-\3', regex=True)
    have = {f[:-8].replace('_', '.') for f in files}
    delta = delta[delta['code'].isin(have)]
    delta = delta.dropna(subset=['open', 'close'])
    print('增量行数=%s 票数=%s 日期=%s..%s 拉取用时%.0fs'
          % (len(delta), delta['code'].nunique(), start, end, time.time() - t0))
    if len(delta) == 0:
        print('MIN5_TDX_SKIP 窗口内无可用增量'); return

    n_ok = n_skip = 0
    cols = ['date', 'time', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount']
    for code, g in delta.groupby('code'):
        out = os.path.join(BASE, code.replace('.', '_') + '.parquet')
        old = pd.read_parquet(out)
        g = g[cols]
        if ovr:
            # overwrite 日期：先删旧行同日，再并入 TDX 行；其余日期旧行赢
            base = old[~old['date'].str.replace('-', '').isin(ovr)]
            new = pd.concat([base, g], ignore_index=True) \
                  .drop_duplicates(subset=['time'], keep='last').sort_values('time')
        else:
            new = pd.concat([old, g], ignore_index=True) \
                  .drop_duplicates(subset=['time'], keep='first').sort_values('time')
        if len(new) > len(old):
            new[cols].to_parquet(out, compression='zstd')
            n_ok += 1
        else:
            n_skip += 1
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    print('MIN5_TDX_DONE 更新=%s 无需动=%s 总用时%.0fs' % (n_ok, n_skip, time.time() - t0))


if __name__ == '__main__':
    main()