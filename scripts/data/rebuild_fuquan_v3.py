#!/usr/bin/env python3
"""
智能前复权重建 v3 — 精准检测 + 只替换除权股
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

def safe_fetch(fn, *args, **kwargs):
    for attempt in range(3):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return None

def fetch_adjusted(code):
    """获取单只股票前复权数据"""
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
    except:
        pass
    return None

def main():
    t0 = datetime.now()
    print(f"🔨 智能前复权重建 v3")
    print(f"   时间: {t0.strftime('%Y-%m-%d %H:%M')}")
    
    conn = duckdb.connect(str(DB_PATH))
    
    # ===== 步骤1: 从备份恢复 =====
    print(f"\n1️⃣  从备份恢复 stock_daily")
    conn.execute("DELETE FROM stock_daily")
    conn.execute("INSERT INTO stock_daily SELECT * FROM stock_daily_bak_pre_fuquan")
    conn.commit()
    restored = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    print(f"   ✅ 已恢复: {restored} 行")
    
    # ===== 步骤2: 检测除权跳空 =====
    print(f"\n2️⃣  检测除权跳空 (gap: (open/prev_close-1)*100 < -8%)")
    
    # 找所有有除权跳空的股票（用窗口函数，高效）
    div_codes = [r[0] for r in conn.execute("""
        SELECT DISTINCT stock_code FROM (
            SELECT stock_code, date, open,
                   LAG(close) OVER (PARTITION BY stock_code ORDER BY date) as prev_close,
                   (open / NULLIF(LAG(close) OVER (PARTITION BY stock_code ORDER BY date), 0) - 1) * 100 as gap_pct
            FROM stock_daily
        ) sub 
        WHERE gap_pct < -8 AND date >= '2026-01-01'
    """).fetchall()]
    
    print(f"   总股票: {conn.execute('SELECT COUNT(DISTINCT stock_code) FROM stock_daily').fetchone()[0]}")
    print(f"   有除权跳空的: {len(div_codes)}")
    print(f"   无需处理的: {restored - len(div_codes)} 只 - 保持原数据 ✅")
    
    if not div_codes:
        print("\n✅ 没有检测到需处理的除权股票！")
        conn.close()
        return
    
    print(f"\n   除权股列表:")
    for c in div_codes[:20]:
        gap = conn.execute(f"""
            SELECT date, prev_close, open, gap_pct FROM (
                SELECT date, close as cur_close, open,
                       LAG(close) OVER (ORDER BY date) as prev_close,
                       (open / NULLIF(LAG(close) OVER (ORDER BY date), 0) - 1) * 100 as gap_pct
                FROM stock_daily WHERE stock_code='{c}'
            ) sub WHERE gap_pct < -8 ORDER BY date DESC LIMIT 2
        """).fetchall()
        for r in gap:
            print(f"   {c}: {r[0]} 前收{r[1]:.2f} 开{r[2]:.2f} 跳空{r[3]:+.2f}%")
    if len(div_codes) > 20:
        print(f"   ... 共{len(div_codes)}只")
    
    # ===== 步骤3: 批量拉取前复权数据 =====
    print(f"\n3️⃣  拉取前复权数据...")
    updated = 0
    failed = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_adjusted, code): code for code in div_codes}
        batch_data = []
        batch_count = 0
        
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    batch_data.append(df)
                else:
                    failed.append(code)
            except Exception as e:
                failed.append(code)
            
            # 每50只批量写入
            if len(batch_data) >= 50 or i == len(div_codes) - 1:
                if batch_data:
                    combined = pd.concat(batch_data, ignore_index=True)
                    keep_cols = ['stock_code', 'date', 'open', 'close', 'high', 'low',
                                 'volume', 'amount', 'amplitude', 'change_pct', 'turn_rate']
                    available = [c for c in keep_cols if c in combined.columns]
                    combined = combined[available]
                    
                    codes_in_batch = combined['stock_code'].unique()
                    codes_str = ', '.join(f"'{c}'" for c in codes_in_batch)
                    conn.execute(f"DELETE FROM stock_daily WHERE stock_code IN ({codes_str})")
                    conn.execute("INSERT INTO stock_daily SELECT * FROM combined")
                    conn.commit()
                    
                    updated += len(codes_in_batch)
                    batch_data = []
            
            if (i + 1) % 30 == 0:
                elapsed = (datetime.now() - t0).seconds
                print(f"   进度: {i+1}/{len(div_codes)}  已更新: {updated}  失败: {len(failed)}  耗时: {elapsed}s")
    
    print(f"   完成! 已更新 {updated} 只, 失败 {len(failed)}")
    
    if failed:
        print(f"   失败列表: {failed[:10]}")
    
    # ===== 验证 =====
    final_cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"📊 最终验证")
    print(f"   总行数: {final_cnt}")
    
    # 重点验证英维克
    yw = conn.execute("""
        SELECT date, open, close, change_pct 
        FROM stock_daily WHERE stock_code='002837' 
        AND date >= '2026-05-20' AND date <= '2026-06-15'
        ORDER BY date
    """).fetchall()
    print(f"\n🔍 英维克:")
    for r in yw:
        print(f"   {r[0]} 开{r[1]:.2f} 收{r[2]:.2f} 涨跌{r[3]:+.2f}%")
    
    # 检查MA和deviation
    ma = conn.execute("""
        WITH prices_asc AS (
            SELECT date, close FROM stock_daily 
            WHERE stock_code='002837' ORDER BY date
        )
        SELECT 
            (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 1) as cur_price,
            (SELECT AVG(close) FROM (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 5)) as ma5,
            (SELECT AVG(close) FROM (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 20)) as ma20,
            (SELECT AVG(close) FROM (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 60)) as ma60
    """).fetchall()
    if ma:
        cur, m5, m20, m60 = ma[0]
        dev60 = (cur/m60 - 1) * 100
        print(f"\n   最新价: {cur:.2f}")
        print(f"   MA5={m5:.2f}  MA20={m20:.2f}  MA60={m60:.2f}")
        print(f"   dev_MA60={dev60:.2f}%")
        print(f"   清仓条件触发? {'✅ 会触发' if (m5 < m20 < m60) and dev60 < -5 else '❌ 不触发'}")
    
    elapsed = (datetime.now() - t0).seconds
    print(f"\n⏱ 总耗时: {elapsed}s ({elapsed/60:.1f}min)")
    conn.close()

if __name__ == '__main__':
    main()
