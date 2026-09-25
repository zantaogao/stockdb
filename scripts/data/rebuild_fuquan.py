#!/usr/bin/env python3
"""
重建 stock_daily 表为前复权数据
用 AKShare adjust='qfq' 逐只股票重新拉取
并行处理加速，分批提交DB
"""
import sys, time, json
from pathlib import Path
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd
import akshare as ak

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'
LOG_PATH = BASE / 'rebuild_fuquan_log.txt'

# AKShare安全调用
def safe_fetch(fn, *args, **kwargs):
    for attempt in range(3):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return None

def fetch_stock_adjusted(code):
    """获取单只股票的前复权日K线"""
    try:
        df = safe_fetch(ak.stock_zh_a_hist, symbol=code, period="daily",
                        start_date="20000101", adjust="qfq")
        if df is not None and not df.empty:
            rename = {
                '日期': 'date', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low',
                '成交量': 'volume', '成交额': 'amount',
                '振幅': 'amplitude', '涨跌幅': 'change_pct',
                '换手率': 'turn_rate'
            }
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            df['stock_code'] = code
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date']).dt.date
            return df
    except Exception as e:
        return None

def main():
    t0 = datetime.now()
    print(f"🔨 开始重建 stock_daily → 前复权")
    print(f"   时间: {t0.strftime('%Y-%m-%d %H:%M')}")
    print(f"   数据库: {DB_PATH}")
    print()

    # 连接DB
    conn = duckdb.connect(str(DB_PATH))
    
    # 读取所有股票代码
    codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code"
    ).fetchall()]
    print(f"📋 共 {len(codes)} 只股票需要处理")
    
    # 读取已有的日期范围（只拉缺失的，减少API调用）
    existing = {}
    for code in codes:
        r = conn.execute(f"SELECT MIN(date), MAX(date) FROM stock_daily WHERE stock_code='{code}'").fetchone()
        existing[code] = (r[0], r[1])
    print(f"   已有数据范围: {min(d[0] for d in existing.values())} ~ {max(d[1] for d in existing.values())}")
    
    # 备份当前表
    print("\n💾 备份 stock_daily → stock_daily_bak_pre_fuquan")
    conn.execute("DROP TABLE IF EXISTS stock_daily_bak_pre_fuquan")
    conn.execute("CREATE TABLE stock_daily_bak_pre_fuquan AS SELECT * FROM stock_daily")
    bak_cnt = conn.execute("SELECT COUNT(*) FROM stock_daily_bak_pre_fuquan").fetchone()[0]
    print(f"   备份完成: {bak_cnt} 行")
    
    # 清空原表（保留结构）
    conn.execute("DELETE FROM stock_daily")
    conn.commit()
    
    # 并行拉取前复权数据
    success = 0
    failed = []
    total = len(codes)
    
    print(f"\n🚀 开始并行拉取前复权数据 (max_workers=10)")
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_stock_adjusted, code): code for code in codes}
        
        batch_data = []
        batch_counter = 0
        
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    batch_data.append(df)
                    success += 1
                else:
                    failed.append((code, "空数据"))
            except Exception as e:
                failed.append((code, str(e)[:50]))
            
            # 每50只股票合并写入一次
            if len(batch_data) >= 50 or i == total - 1:
                if batch_data:
                    combined = pd.concat(batch_data, ignore_index=True)
                    # 只保留需要的列
                    keep_cols = ['stock_code', 'date', 'open', 'close', 'high', 'low',
                                 'volume', 'amount', 'amplitude', 'change_pct', 'turn_rate']
                    available = [c for c in keep_cols if c in combined.columns]
                    combined = combined[available]
                    
                    conn.execute("INSERT INTO stock_daily SELECT * FROM combined")
                    conn.commit()
                    
                    batch_counter += len(batch_data)
                    batch_data = []
            
            # 进度
            if (i + 1) % 100 == 0:
                elapsed = (datetime.now() - t0).seconds
                rate = (i + 1) / max(elapsed, 1)
                eta = (total - i - 1) / max(rate, 0.1)
                print(f"   进度: {i+1}/{total}  成功: {success}  失败: {len(failed)}  耗时: {elapsed}s  ETA: {eta:.0f}s")
    
    # 写入最后的批次
    if batch_data:
        combined = pd.concat(batch_data, ignore_index=True)
        keep_cols = ['stock_code', 'date', 'open', 'close', 'high', 'low',
                     'volume', 'amount', 'amplitude', 'change_pct', 'turn_rate']
        available = [c for c in keep_cols if c in combined.columns]
        combined = combined[available]
        conn.execute("INSERT INTO stock_daily SELECT * FROM combined")
        conn.commit()
    
    # 验证
    new_cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    new_codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
    new_dates = conn.execute("SELECT MIN(date), MAX(date) FROM stock_daily").fetchone()
    
    print(f"\n{'='*60}")
    print(f"📊 重建完成!")
    print(f"   原数据: {bak_cnt} 行 / {len(codes)} 只股票")
    print(f"   新数据: {new_cnt} 行 / {new_codes} 只股票")
    print(f"   日期范围: {new_dates[0]} ~ {new_dates[1]}")
    print(f"   成功: {success}  失败: {len(failed)}")
    
    if failed:
        print(f"\n⚠️ 失败股票 ({len(failed)}只):")
        for c, reason in failed[:20]:
            print(f"   {c}: {reason}")
        if len(failed) > 20:
            print(f"   ... 还有 {len(failed)-20} 只")
    
    elapsed = (datetime.now() - t0).seconds
    print(f"\n⏱ 总耗时: {elapsed}s ({elapsed/60:.1f}min)")
    
    # 验证英维克
    yw = conn.execute("""
        SELECT date, open, close, change_pct 
        FROM stock_daily WHERE stock_code='002837' 
        AND date >= '2026-05-20' AND date <= '2026-06-15'
        ORDER BY date
    """).fetchall()
    print(f"\n🔍 英维克前复权验证:")
    for r in yw:
        print(f"   {r[0]} 开{r[1]:.2f} 收{r[2]:.2f} 涨跌{r[3]:+.2f}%")
    
    conn.close()
    
    # 写日志
    with open(LOG_PATH, 'w') as f:
        json.dump({
            'timestamp': t0.isoformat(),
            'total_stocks': len(codes),
            'success': success,
            'failed': len(failed),
            'failed_list': failed[:100],
            'new_rows': new_cnt,
            'new_codes': new_codes,
            'date_range': [str(new_dates[0]), str(new_dates[1])],
            'elapsed_seconds': elapsed,
        }, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
