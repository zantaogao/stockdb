#!/usr/bin/env python3
"""
智能前复权重建 — 只重建有除权的股票
1. 从备份恢复 stock_daily
2. 识别有除权的股票（检测大跳空）
3. 只对这些股票重新拉取AKShare前复权数据
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

def has_dividend_gap(conn, code, threshold=-10):
    """检测股票是否有除权缺口（120天内）"""
    r = conn.execute(f"""
        SELECT COUNT(*) FROM stock_daily 
        WHERE stock_code='{code}' 
        AND change_pct < {threshold}
    """).fetchone()
    return r[0] > 0

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
    print(f"🔨 智能前复权重建")
    print(f"   时间: {t0.strftime('%Y-%m-%d %H:%M')}")
    
    conn = duckdb.connect(str(DB_PATH))
    
    # ===== 步骤1: 从备份恢复 =====
    print(f"\n1️⃣  从备份恢复 stock_daily")
    bak_cnt = conn.execute("SELECT COUNT(*) FROM stock_daily_bak_pre_fuquan").fetchone()[0]
    print(f"   备份表: {bak_cnt} 行")
    
    # 清空当前表后从备份恢复
    conn.execute("DELETE FROM stock_daily")
    conn.execute("INSERT INTO stock_daily SELECT * FROM stock_daily_bak_pre_fuquan")
    conn.commit()
    
    restored = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    print(f"   ✅ 已恢复: {restored} 行到 stock_daily")
    
    # ===== 步骤2: 识别除权股 =====
    print(f"\n2️⃣  扫描除权股票")
    all_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code"
    ).fetchall()]
    
    # 先找-10%以下的跳空（大概率除权）
    div_candidates = []
    for code in all_codes:
        if has_dividend_gap(conn, code):
            div_candidates.append(code)
    
    print(f"   总股票: {len(all_codes)}")
    print(f"   有除权跳空的: {len(div_candidates)}")
    print(f"   无需处理的: {len(all_codes) - len(div_candidates)}")
    
    if not div_candidates:
        print("\n✅ 无需重建，没有股票有除权缺口！")
        conn.close()
        return
    
    # ===== 步骤3: 并行拉取前复权数据 =====
    print(f"\n3️⃣  拉取除权股票的前复权数据 (max_workers=10)")
    
    # 收集要更新的股票
    to_update = {}
    success = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_adjusted, code): code for code in div_candidates}
        
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    to_update[code] = df
                    success += 1
                else:
                    failed += 1
                    print(f"   ⚠️ {code}: 获取失败(空)")
            except Exception as e:
                failed += 1
                print(f"   ⚠️ {code}: {str(e)[:50]}")
            
            if (i + 1) % 50 == 0:
                elapsed = (datetime.now() - t0).seconds
                print(f"   进度: {i+1}/{len(div_candidates)}  成功: {len(to_update)}  失败: {failed}  耗时: {elapsed}s")
    
    print(f"\n   拉取完成: 成功={len(to_update)} 失败={failed}")
    
    # ===== 步骤4: 更新DB =====
    print(f"\n4️⃣  写入前复权数据到DB")
    batch_size = 100
    total_updated = 0
    
    codes_list = list(to_update.keys())
    for i in range(0, len(codes_list), batch_size):
        batch_codes = codes_list[i:i+batch_size]
        batch_dfs = []
        
        for code in batch_codes:
            df = to_update[code]
            batch_dfs.append(df)
        
        if batch_dfs:
            combined = pd.concat(batch_dfs, ignore_index=True)
            keep_cols = ['stock_code', 'date', 'open', 'close', 'high', 'low',
                         'volume', 'amount', 'amplitude', 'change_pct', 'turn_rate']
            available = [c for c in keep_cols if c in combined.columns]
            combined = combined[available]
            
            # 删除这些股票的旧数据
            codes_str = ', '.join(f"'{c}'" for c in batch_codes)
            conn.execute(f"DELETE FROM stock_daily WHERE stock_code IN ({codes_str})")
            
            # 插入新数据
            conn.execute("INSERT INTO stock_daily SELECT * FROM combined")
            conn.commit()
            
            total_updated += len(batch_codes)
        
        if (i + batch_size) % 200 == 0 or i + batch_size >= len(codes_list):
            print(f"   已更新 {min(i+batch_size, len(codes_list))}/{len(codes_list)} 只股票")
    
    # ===== 验证 =====
    new_cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    new_codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
    
    print(f"\n{'='*60}")
    print(f"📊 重建完成!")
    print(f"   总行数: {new_cnt}")
    print(f"   股票数: {new_codes}")
    print(f"   更新了 {total_updated} 只除权股票的前复权数据")
    
    # 验证英维克
    yw = conn.execute("""
        SELECT date, open, close, change_pct 
        FROM stock_daily WHERE stock_code='002837' 
        AND date >= '2026-05-20' AND date <= '2026-06-15'
        ORDER BY date
    """).fetchall()
    print(f"\n🔍 英维克前复权验证:")
    if yw:
        for r in yw:
            print(f"   {r[0]} 开{r[1]:.2f} 收{r[2]:.2f} 涨跌{r[3]:+.2f}%")
        # 检查6月1日涨跌幅
        jun1 = [r for r in yw if '2026-06-01' in str(r[0])]
        if jun1:
            print(f"\n   6月1日涨跌幅: {jun1[0][3]:+.2f}% (期望: < -10% → 仍有除权跳空)")
            print(f"   如果前复权生效, 6月1日涨跌幅应为 ~{yw[8][3]:+.2f}% 左右的小幅下跌")
    else:
        print("   ❌ 没有英维克数据!")
    
    elapsed = (datetime.now() - t0).seconds
    print(f"\n⏱ 总耗时: {elapsed}s ({elapsed/60:.1f}min)")
    conn.close()

if __name__ == '__main__':
    main()
