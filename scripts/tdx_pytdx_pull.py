#!/usr/bin/env python3
"""pytdx 直连通达信行情服务器，拉全市场 1分钟/5分钟线（2026-08-16 PC 同步停用后主源）
用法: python3 -B scripts/tdx_pytdx_pull.py [days] [outdir]
  days  = 拉最近几个交易日（默认 5，1分钟线服务器只保留约 13 个交易日）
  outdir = CSV 输出目录（默认 /tmp，文件名 tdx_min1_recent.csv / tdx_min5_recent.csv，
           与 PC 导出格式完全一致，供 tdx_archive.py / tdx_import_csv.py 无缝衔接）
CSV 格式: code,market,datetime(YYYYMMDD HHMM),open,high,low,close,amount,volume
"""
import sys, os, csv, time, math, socket
socket.setdefaulttimeout(15)  # 2026-09-10: pytdx recv 无超时保护，服务器连接后不应答会永久阻塞
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from pytdx.hq import TdxHq_API

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
OUTDIR = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/tmp')
OUT1 = OUTDIR / 'tdx_min1_recent.csv'
OUT5 = OUTDIR / 'tdx_min5_recent.csv'

# 通达信行情服务器池（2026-09-10 全量实测 mootdx 141 台列表后的可用 9 台 + 原 2 台兜底）。
# 启动时逐台做业务级探针（真拉K线，连接成功但空返回的淘汰）——
# 09-10 实锤：主服务器 TCP 能连但业务查询全空，只有部分服务器（国泰君安/安信）有数据。
SERVERS = [
    ('117.34.114.13', 7709),   # 国泰君安
    ('117.34.114.14', 7709),
    ('117.34.114.15', 7709),
    ('117.34.114.16', 7709),
    ('117.34.114.17', 7709),
    ('117.34.114.18', 7709),
    ('117.34.114.20', 7709),
    ('117.34.114.27', 7709),
    ('59.36.5.11', 7709),      # 安信
    ('218.75.126.9', 7709),    # 原主源（杭州电信J3），可能 EMPTY，探针自动淘汰
    ('115.238.90.165', 7709),  # 原备源（杭州电信J4）
]

def probe_live(host, port, timeout=5):
    """业务级探针：连上且真能返回 1分钟K线才算活。返回 (ok, 最新bar时间)。"""
    api = TdxHq_API()
    try:
        if not api.connect(host, port, time_out=timeout):
            return False, ''
        bars = api.get_security_bars(8, 0, '000001', 0, 10)
        ok = bool(bars)
        last = bars[-1].get('datetime', '') if bars else ''
        return ok, last
    except Exception:
        return False, ''
    finally:
        try:
            api.disconnect()
        except Exception:
            pass

def select_servers():
    """逐台探针，返回业务上真能出数据的服务器列表（全空则返回空列表）。"""
    live = []
    for host, port in SERVERS:
        ok, last = probe_live(host, port)
        print(f"  探针 {host}:{port} -> {'OK ' + last if ok else 'EMPTY/FAIL'}", flush=True)
        if ok:
            live.append((host, port))
        if len(live) >= 4:   # 4 台足够 8 并发用，不再浪费时间探剩下的
            break
    return live

def get_stock_list():
    """全市场股票列表: (6位代码, 市场号 0=深 1=沪 2=北交所)"""
    import duckdb
    d = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
    rows = d.execute("SELECT ts_code FROM stock_basic").fetchall()
    out = []
    for (ts,) in rows:
        code6 = ts.split('.')[0]
        if code6.startswith(('6', '9')):
            mkt = 1
        elif code6.startswith(('0', '3')):
            mkt = 0
        else:
            mkt = 2  # 北交所 4/8/92 开头
        out.append((code6, mkt))
    return out

def bars_to_rows(code, mkt, bars):
    """pytdx bar → CSV 行。volume 单位=手，与 PC 导出对齐（PC 也是 mootdx 同源）"""
    rows = []
    for b in bars:
        dt = b.get('datetime', '')  # 'YYYY-MM-DD HH:MM'
        dt_compact = dt.replace('-', '').replace(':', '').replace(' ', ' ')
        # 转成 YYYYMMDD HHMM
        if len(dt_compact) == 13:  # YYYYMMDD HHMM
            ds = dt_compact[:8]
            tm = dt_compact[9:13]
        else:
            continue
        vol = b.get('vol', 0) or 0
        amt = b.get('amount', 0) or 0
        if not amt:
            amt = round(vol * b.get('close', 0), 2)  # 近似（PC 导出 amount 也常为 0）
        rows.append((code, 'sh' if mkt == 1 else ('bj' if mkt == 2 else 'sz'),
                     f"{ds} {tm}", b.get('open'), b.get('high'),
                     b.get('low'), b.get('close'), amt, vol))
    return rows

def pull_stock(api, code, mkt, days, cat, max_pages):
    """拉一只股票的分钟线，翻页直到覆盖 days 个交易日"""
    rows = []
    start = 0
    for _ in range(max_pages):
        try:
            bars = api.get_security_bars(cat, mkt, code, start, 800)
        except Exception:
            break
        if not bars:
            break
        rows.extend(bars_to_rows(code, mkt, bars))
        # 已覆盖目标天数则停（1分钟线 800根≈3.3交易日）
        if len(rows) >= days * 240 + 100:
            break
        start += 800
    return rows

def worker(args):
    code, mkt, days, live_servers = args
    api = TdxHq_API()
    for host, port in live_servers:
        try:
            if api.connect(host, port, time_out=6):
                break
        except Exception:
            continue
    else:
        return code, None
    try:
        r1 = pull_stock(api, code, mkt, days, 8, 4)    # 1分钟
        r5 = pull_stock(api, code, mkt, days, 0, 2)    # 5分钟
        return code, (r1, r5)
    finally:
        try:
            api.disconnect()
        except Exception:
            pass

def main():
    print('服务器业务级探针：', flush=True)
    live = select_servers()
    if not live:
        print("⚠️ EMPTY: 全部服务器探针均无数据返回，判为失败")
        sys.exit(1)
    stocks = get_stock_list()
    print(f"可用服务器 {len(live)} 台，股票数: {len(stocks)}，拉取 {DAYS} 个交易日（1分钟+5分钟）")
    t0 = time.time()
    results = {}
    # 8 并发（每线程独立连接）
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(worker, (c, m, DAYS, live)): c for c, m in stocks}
        done = 0
        for fut in as_completed(futs):
            code, data = fut.result()
            if data is not None:
                results[code] = data
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(stocks)} 完成，{time.time()-t0:.0f}s")
    print(f"拉取完成: {len(results)}/{len(stocks)} 只有数据，耗时 {time.time()-t0:.0f}s")

    # 写 CSV（与 PC 导出同格式）
    n1 = n5 = 0
    with open(OUT1, 'w', newline='') as f1, open(OUT5, 'w', newline='') as f5:
        w1 = csv.writer(f1); w5 = csv.writer(f5)
        w1.writerow(['code', 'market', 'datetime', 'open', 'high', 'low', 'close', 'amount', 'volume'])
        w5.writerow(['code', 'market', 'datetime', 'open', 'high', 'low', 'close', 'amount', 'volume'])
        for code, (r1, r5) in results.items():
            if r1:
                w1.writerows(r1); n1 += len(r1)
            if r5:
                w5.writerows(r5); n5 += len(r5)
    print(f"✅ {OUT1}: {n1} 行")
    print(f"✅ {OUT5}: {n5} 行")
    # EMPTY 即失败（2026-09-10 拍板）：服务器空返回时 pytdx 连接全成功、退 0 = cron 假绿灯
    # （0910 实锤：5900/5900 连接成功但 0 行）。min1 为 0 行 → 退 1，让 tdx_sync.sh 中止并告警。
    if n1 == 0:
        print("⚠️ EMPTY: 行情服务器空返回（连接成功但 0 行），判为失败")
        sys.exit(1)

if __name__ == '__main__':
    main()
