#!/usr/bin/env python3
"""A股数据每日增量更新脚本
用法: python stock_update_daily.py
自动检测每个股票的最新日期，只拉取新数据增量写入
"""

import os, sys, time, json
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd
import akshare as ak
from tqdm import tqdm
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_PATH = os.path.expanduser("~/.hermes/stockdb/stock.db")
MAX_WORKERS = 1
REQUEST_DELAY = 0.5  # 每只股票间等待，防止API封IP
TODAY = date.today()

# Per-script session with retry for all akshare HTTP requests
_ak_session = None
def get_ak_session():
    global _ak_session
    if _ak_session is None:
        _ak_session = requests.Session()
        retries = Retry(total=3, backoff_factor=5, status_forcelist=[429, 500, 502, 503, 504])
        _ak_session.mount('https://', HTTPAdapter(max_retries=retries, pool_maxsize=4))
        _ak_session.mount('http://', HTTPAdapter(max_retries=retries, pool_maxsize=4))
        _ak_session.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
    return _ak_session

# Monkey-patch requests.get to use our persistent session
_original_get = requests.get
def _patched_get(url, **kwargs):
    kwargs.setdefault('timeout', 30)
    return get_ak_session().get(url, **kwargs)
requests.get = _patched_get

def get_db():
    return duckdb.connect(DB_PATH)

def get_last_dates(db):
    """获取每只股票的最新日期"""
    rows = db.execute(
        "SELECT stock_code, MAX(date) FROM stock_daily GROUP BY stock_code"
    ).fetchall()
    return {r[0]: r[1] for r in rows}  # code -> latest_date

def _get_market_prefix(code):
    """根据股票代码前缀判断市场"""
    if code.startswith(('6', '9')):
        return 'sh'
    return 'sz'

def _fetch_from_em(code, start_str, end_str):
    """从东方财富（主数据源）获取数据"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_str, end_date=end_str, adjust="qfq"
        )
        if df is None or df.empty:
            return None

        rename = {
            '日期': 'date', '开盘': 'open', '收盘': 'close',
            '最高': 'high', '最低': 'low',
            '成交量': 'volume', '成交额': 'amount',
            '振幅': 'amplitude', '涨跌幅': 'change_pct', '换手率': 'turn_rate'
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        return df
    except Exception as e:
        if 'ConnectionError' in type(e).__name__ or 'RemoteDisconnected' in type(e).__name__:
            return None  # EM不可用，触发fallback
        raise

def _fetch_from_sina(code, start_str, end_str):
    """从新浪财经（备用数据源）获取数据，用于东方财富不可用时的降级"""
    try:
        market = _get_market_prefix(code)
        sina_symbol = f"{market}{code}"
        df = ak.stock_zh_a_daily(
            symbol=sina_symbol, start_date=start_str, end_date=end_str, adjust="qfq"
        )
        if df is None or df.empty:
            return None
        # stock_zh_a_daily 返回的列: date, open, high, low, close, volume, amount, outstanding_share, turnover
        # 缺少: amplitude(振幅), change_pct(涨跌幅); turnover=换手率
        df['amplitude'] = None
        df['change_pct'] = None
        df['turn_rate'] = df['turnover']
        return df
    except Exception as e:
        print(f"    ⚠️ Sina fallback 失败: {type(e).__name__}: {e}", flush=True)
        return None

def fetch_incremental(code, start_date):
    """增量拉取某只股票的数据，带自动重试，支持EM/Sina双数据源"""
    start_str = start_date.strftime('%Y%m%d')
    end_str = TODAY.strftime('%Y%m%d')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 优先使用东方财富
            df = _fetch_from_em(code, start_str, end_str)
            if df is None:
                # EM不可用，尝试新浪
                df = _fetch_from_sina(code, start_str, end_str)
            if df is None or df.empty:
                return code, 0, None

            df['stock_code'] = code
            df['date'] = pd.to_datetime(df['date']).dt.date

            return code, df, None
        except Exception as e:
            if attempt < max_retries - 1:
                sleep_time = 10 * (2 ** attempt)  # 10s, 20s, 40s
                print(f"  ⏳ {code} 重试 ({attempt+1}/{max_retries}) 等待{sleep_time}s: {type(e).__name__}", flush=True)
                time.sleep(sleep_time)
            else:
                return code, pd.DataFrame(), str(e)

def update_daily():
    print(f"\n📊 股票日K线增量更新 — {TODAY}")

    # 用短连接获取初始信息，不保留持久连接（避免与线程内的连接冲突）
    init_db = duckdb.connect(DB_PATH)
    count = init_db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    if count == 0:
        print("❌ 数据库为空，请先运行 build_stock_db.py 完成首次全量拉取")
        init_db.close()
        return

    last_dates = get_last_dates(init_db)
    init_db.close()
    codes = list(last_dates.keys())
    print(f"  共 {len(codes)} 只股票")

    # 筛选需要更新的（最新日期 < today）
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

    def process(item):
        code, ld = item
        try:
            result = fetch_incremental(code, ld)
            code, df, err = result
            if err:
                return code, 0, err
            if df is not None and not df.empty:
                time.sleep(REQUEST_DELAY)  # 减速防封
                # 每个线程使用独立连接，写完关闭
                local_db = duckdb.connect(DB_PATH)
                try:
                    new_count = 0
                    local_db.execute("BEGIN TRANSACTION")
                    for _, row in df.iterrows():
                        row_date = row['date']
                        if row_date > ld:  # 只插新数据
                            local_db.execute(
                                """INSERT OR REPLACE INTO stock_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                [
                                    code, str(row_date),
                                    float(row.get('open', 0)) if pd.notna(row.get('open')) else None,
                                    float(row.get('close', 0)) if pd.notna(row.get('close')) else None,
                                    float(row.get('high', 0)) if pd.notna(row.get('high')) else None,
                                    float(row.get('low', 0)) if pd.notna(row.get('low')) else None,
                                    int(row.get('volume', 0)) if pd.notna(row.get('volume')) else None,
                                    float(row.get('amount', 0)) if pd.notna(row.get('amount')) else None,
                                    float(row.get('amplitude', 0)) if pd.notna(row.get('amplitude')) else None,
                                    float(row.get('change_pct', 0)) if pd.notna(row.get('change_pct')) else None,
                                    float(row.get('turn_rate', 0)) if pd.notna(row.get('turn_rate')) else None,
                                ]
                            )
                            new_count += 1
                    local_db.execute("COMMIT")
                    return code, new_count, None
                finally:
                    local_db.close()
            return code, 0, None
        except Exception as e:
            return code, 0, str(e)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process, item): item[0] for item in codes_to_update}
        for future in tqdm(as_completed(futures), total=len(codes_to_update), desc="增量更新"):
            code, rows, err = future.result()
            if err:
                failed += 1
            else:
                total_rows += rows

    # 短连接获取最终统计
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

def update_board():
    """增量更新行业板块日线"""
    print(f"\n📊 板块日线增量更新 — {TODAY}")

    init_db = duckdb.connect(DB_PATH)
    count = init_db.execute("SELECT COUNT(*) FROM board_daily").fetchone()[0]
    if count == 0:
        print("  ⏭ 板块数据为空，跳过")
        init_db.close()
        return

    boards = init_db.execute(
        "SELECT DISTINCT board_code FROM board_daily"
    ).fetchdf()['board_code'].tolist()
    init_db.close()

    print(f"  共 {len(boards)} 个板块")
    total_rows = 0

    def process(code):
        try:
            df = ak.stock_board_industry_hist_em(code)
            if df is not None and not df.empty:
                rename = {
                    '日期': 'date', '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low',
                    '成交量': 'volume', '成交额': 'amount', '涨跌幅': 'change_pct'
                }
                df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
                df['board_code'] = code
                df['date'] = pd.to_datetime(df['date']).dt.date

                # 每个线程独立连接，查最新日期 + 写入
                local_db = duckdb.connect(DB_PATH)
                try:
                    last_row = local_db.execute(
                        "SELECT MAX(date) FROM board_daily WHERE board_code=?", [code]
                    ).fetchone()[0]
                    new_count = 0
                    local_db.execute("BEGIN TRANSACTION")
                    for _, row in df.iterrows():
                        rd = row['date']
                        if last_row is None or rd > last_row:
                            local_db.execute(
                                """INSERT OR REPLACE INTO board_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                [
                                    code, str(rd),
                                    float(row.get('open', 0)) if pd.notna(row.get('open')) else None,
                                    float(row.get('close', 0)) if pd.notna(row.get('close')) else None,
                                    float(row.get('high', 0)) if pd.notna(row.get('high')) else None,
                                    float(row.get('low', 0)) if pd.notna(row.get('low')) else None,
                                    int(row.get('volume', 0)) if pd.notna(row.get('volume')) else None,
                                    float(row.get('amount', 0)) if pd.notna(row.get('amount')) else None,
                                    float(row.get('change_pct', 0)) if pd.notna(row.get('change_pct')) else None,
                                ]
                            )
                            new_count += 1
                    local_db.execute("COMMIT")
                    return new_count
                finally:
                    local_db.close()
            return 0
        except:
            return 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process, code): code for code in boards}
        for future in tqdm(as_completed(futures), total=len(boards), desc="板块"):
            total_rows += future.result()

    print(f"  ✅ 板块更新: 新增 {total_rows} 行")

def update_index():
    """增量更新指数日线"""
    print(f"\n📊 指数日线增量更新 — {TODAY}")
    db = get_db()

    count = db.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0]
    if count == 0:
        print("  ⏭ 指数数据为空，跳过")
        db.close()
        return

    indexes = {'sh000001': '上证指数', 'sz399001': '深证成指', 'sz399006': '创业板指',
               'sh000688': '科创50', 'sh000300': '沪深300', 'sh000016': '上证50',
               'sh000905': '中证500', 'sz399852': '中证1000'}
    total_rows = 0

    for symbol, name in indexes.items():
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is not None and not df.empty:
                rename = {
                    'date': 'date', 'open': 'open', 'close': 'close',
                    'high': 'high', 'low': 'low',
                    'volume': 'volume', 'amount': 'amount', 'pctChange': 'change_pct'
                }
                df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
                # Extract code (strip sh/sz prefix)
                code = symbol[2:] if symbol.startswith(('sh','sz')) else symbol
                df['index_code'] = code
                df['date'] = pd.to_datetime(df['date']).dt.date

                last_row = db.execute(
                    "SELECT MAX(date) FROM index_daily WHERE index_code=?", [code]
                ).fetchone()[0]

                new_count = 0
                for _, row in df.iterrows():
                    rd = row['date']
                    if last_row is None or rd > last_row:
                        db.execute(
                            """INSERT OR REPLACE INTO index_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [code, str(rd),
                             float(row.get('open', 0)) if pd.notna(row.get('open')) else None,
                             float(row.get('close', 0)) if pd.notna(row.get('close')) else None,
                             float(row.get('high', 0)) if pd.notna(row.get('high')) else None,
                             float(row.get('low', 0)) if pd.notna(row.get('low')) else None,
                             int(row.get('volume', 0)) if pd.notna(row.get('volume')) else None,
                             float(row.get('amount', 0)) if pd.notna(row.get('amount')) else None,
                             float(row.get('change_pct', 0)) if pd.notna(row.get('change_pct')) else None,
                             ]
                        )
                        new_count += 1
                total_rows += new_count
                if new_count > 0:
                    print(f"    ✅ {name}: +{new_count}")
        except Exception as e:
            print(f"    ⚠️ {name}: {e}")
        time.sleep(0.5)

    print(f"  ✅ 指数更新完成: 新增 {total_rows} 行")
    db.close()

if __name__ == '__main__':
    print(f"========== A股数据增量更新 {datetime.now().strftime('%Y-%m-%d %H:%M')} ==========")
    update_daily()
    try:
        update_board()
    except Exception as e:
        print(f"  ⚠️ 板块更新异常 (已跳过): {e}")
    try:
        update_index()
    except Exception as e:
        print(f"  ⚠️ 指数更新异常 (已跳过): {e}")
    print(f"\n✅ 增量更新完成")
