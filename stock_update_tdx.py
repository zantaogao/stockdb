#!/usr/bin/env python3
"""A股日K增量更新 — 纯pytdx数据源（不依赖PC/东方财富）
用法: python stock_update_tdx.py
"""
import os, sys, time, threading, json
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import duckdb
import pandas as pd
from pytdx.hq import TdxHq_API

DB_PATH = os.path.expanduser("~/.hermes/stockdb/stock.db")
MAX_WORKERS = 6
TODAY = date.today()

# 线程安全 API
_tlocal = threading.local()
def get_api():
    if not hasattr(_tlocal, 'api') or _tlocal.api is None:
        _tlocal.api = TdxHq_API(heartbeat=False)
        _tlocal.api.connect('180.153.18.172', 80, time_out=10)
    return _tlocal.api

def get_last_dates(db):
    """获取每只股票的最新日期"""
    rows = db.execute(
        "SELECT stock_code, MAX(date) FROM stock_daily GROUP BY stock_code"
    ).fetchall()
    return {r[0]: r[1] for r in rows}

def get_market(code):
    """通达信市场编号"""
    return 1 if code.startswith(('6', '9')) else 0

def fetch_bars(code, market, after_date):
    """拉取 after_date 之后的 K 线"""
    api = get_api()
    # 先拉最近 800 根（覆盖约 3-4 年），再筛选
    try:
        bars = api.get_security_bars(9, market, code, 0, 800)
        if not bars:
            return code, []
        # 只保留 after_date 之后的
        new_bars = []
        for b in bars:
            d = date(b['year'], b['month'], b['day'])
            if d > after_date and d <= TODAY:
                new_bars.append(b)
        return code, new_bars
    except Exception as e:
        return code, []

def update_daily():
    print(f"\n📊 股票日K增量更新 (pytdx) — {TODAY}")
    
    init_db = duckdb.connect(DB_PATH)
    count = init_db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    if count == 0:
        print("❌ 数据库为空，请先运行 build_stock_db.py 完成首次全量拉取")
        init_db.close()
        return

    last_dates = get_last_dates(init_db)
    codes = list(last_dates.keys())
    init_db.close()
    print(f"  共 {len(codes)} 只股票")

    # 筛选需要更新的
    codes_to_update = []
    for code in codes:
        ld = last_dates[code]
        if ld is None or ld < TODAY:
            codes_to_update.append((code, ld if ld else date(2016, 1, 1)))

    if not codes_to_update:
        print("  ✅ 所有股票数据已是最新，无需更新")
        return

    print(f"  需要更新: {len(codes_to_update)} 只")

    total_rows = 0
    failed = 0
    BATCH = 200

    for batch_start in range(0, len(codes_to_update), BATCH):
        batch = codes_to_update[batch_start:batch_start + BATCH]
        results = {}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for code, ld in batch:
                m = get_market(code)
                futures[executor.submit(fetch_bars, code, m, ld)] = code
            for f in tqdm(as_completed(futures), total=len(batch), desc="拉取增量"):
                code, bars = f.result()
                if bars:
                    results[code] = bars

        # 批量写入
        if results:
            rows = []
            for code, bars in results.items():
                for b in sorted(bars, key=lambda x: (x['year'], x['month'], x['day'])):
                    d = f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}"
                    rows.append((
                        code, d,
                        b['open'], b['close'], b['high'], b['low'],
                        b['vol'] * 100, b['amount'],
                        None, None, None  # amplitude, change_pct, turn_rate
                    ))

            if rows:
                cols = ['stock_code','date','open','close','high','low','volume','amount','amplitude','change_pct','turn_rate']
                df = pd.DataFrame(rows, columns=cols)
                write_db = duckdb.connect(DB_PATH)
                write_db.execute("INSERT OR REPLACE INTO stock_daily SELECT * FROM df")
                write_db.commit()
                write_db.close()
                total_rows += len(rows)

        print(f"  📊 累计新增: {total_rows} 行")

    final_db = duckdb.connect(DB_PATH)
    new_count = final_db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    total_stocks = final_db.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
    final_db.close()

    print(f"\n  ✅ 更新完成")
    print(f"  新增行数: {total_rows}")
    print(f"  总行数: {new_count}")
    print(f"  有数据的股票: {total_stocks}")
    if failed:
        print(f"  ⚠️ 失败: {failed} 只")

if __name__ == '__main__':
    print(f"========== A股数据增量更新 (pytdx) {datetime.now().strftime('%Y-%m-%d %H:%M')} ==========")
    update_daily()
    print(f"\n✅ 增量更新完成")
