#!/usr/bin/env python3
"""
数据库内前复权计算 — 不需要API调用
原理：对每只股票检测除权跳空，计算复权因子，然后调整历史价格
"""
import json, time
from pathlib import Path
from datetime import datetime
import duckdb
import numpy as np

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'

def main():
    t0 = datetime.now()
    conn = duckdb.connect(str(DB_PATH))
    
    print(f"🔨 数据库内前复权计算")
    print(f"   时间: {t0.strftime('%Y-%m-%d %H:%M')}")
    
    # ===== 1. 如果需要，先从备份恢复 =====
    cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    if cnt == 0:
        print("\n⚠️ stock_daily 为空，从备份恢复...")
        conn.execute("INSERT INTO stock_daily SELECT * FROM stock_daily_bak_pre_fuquan")
        conn.commit()
        cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
        print(f"   已恢复: {cnt} 行")
    
    # ===== 2. 识别所有除权事件 =====
    print(f"\n1️⃣ 扫描除权事件...")
    div_events = conn.execute("""
        SELECT stock_code, date, prev_close, open, gap_pct FROM (
            SELECT stock_code, date, 
                   LAG(close) OVER (PARTITION BY stock_code ORDER BY date) as prev_close,
                   open, close,
                   (open / NULLIF(LAG(close) OVER (PARTITION BY stock_code ORDER BY date), 0) - 1) * 100 as gap_pct
            FROM stock_daily
        ) sub 
        WHERE gap_pct < -8
        ORDER BY stock_code, date
    """).fetchall()
    
    print(f"   共 {len(div_events)} 个除权事件")
    
    if not div_events:
        print("   ✅ 无除权事件，无需处理!")
        conn.close()
        return
    
    # ===== 3. 按股票分组计算累积复权因子 =====
    print(f"\n2️⃣ 计算复权因子...")
    
    # 按股票分组
    stock_events = {}
    for evt in div_events:
        code = evt[0]
        if code not in stock_events:
            stock_events[code] = []
        stock_events[code].append({
            'date': evt[1],
            'prev_close': evt[2],
            'open': evt[3],
            'gap_pct': evt[4]
        })
    
    print(f"   涉及 {len(stock_events)} 只股票")
    
    # ===== 4. 对每只股票应用前复权 =====
    print(f"\n3️⃣ 应用前复权调整...")
    
    updated = 0
    batch_size = 20
    stock_list = sorted(stock_events.keys())
    
    for i, code in enumerate(stock_list):
        events = stock_events[code]
        
        # 计算累积调整因子（按日期升序，最早的事件先算）
        # 前复权：对于日期在事件之前的行，乘以调整因子
        # 注意：多个事件时，因子是累积的
        
        # 先按日期排序事件
        events_sorted = sorted(events, key=lambda x: x['date'])
        
        # 获取这个股票的所有价格数据（升序）
        rows = conn.execute(f"""
            SELECT date, open, close, high, low, volume, amount, change_pct, turn_rate
            FROM stock_daily WHERE stock_code='{code}'
            ORDER BY date
        """).fetchall()
        
        if len(rows) < 60:
            continue
        
        # 构建累积因子
        # 从最新到最旧：对于每笔除权，因子 = 除权后开盘 / 除权前收盘
        # 累积因子从最近向前计算
        
        # 方法：从最新的数据往前调
        # 获取所有日期和调整因子
        adj_factors = {}  # date -> cumulative factor to apply
        
        # 从最近的除权开始算累积因子
        events_by_date = {}
        for evt in events_sorted:
            d_str = str(evt['date'])
            factor = evt['open'] / evt['prev_close']
            events_by_date[d_str] = factor
        
        # 对于每行数据，找到它之后最近的一次除权
        dates = [str(r[0]) for r in rows]
        
        # 前复权因子计算:
        # 对于每行，它的调整因子 = 它之后所有除权因子相乘
        # 因为我们从后往前累积
        cumulative_factor = 1.0
        row_factors = []
        
        for dt in reversed(dates):
            if dt in events_by_date:
                cumulative_factor *= events_by_date[dt]
            row_factors.append(cumulative_factor)
        
        row_factors = list(reversed(row_factors))
        
        # 应用调整
        updates = []
        for j, r in enumerate(rows):
            fac = row_factors[j]
            if abs(fac - 1.0) < 0.001:  # 因子接近1，无需调整
                continue
            
            dt, op, cl, hi, lo, vol, amt, chg, turn = r
            
            new_op = round(op * fac, 2)
            new_cl = round(cl * fac, 2)
            new_hi = round(hi * fac, 2)
            new_lo = round(lo * fac, 2)
            
            updates.append((new_op, new_cl, new_hi, new_lo, code, str(dt)))
        
        # 批量更新
        if updates:
            # 使用临时表批量更新
            conn.execute("BEGIN TRANSACTION")
            for upd in updates:
                new_op, new_cl, new_hi, new_lo, c, dt = upd
                conn.execute(f"""
                    UPDATE stock_daily SET 
                        open={new_op}, close={new_cl}, high={new_hi}, low={new_lo}
                    WHERE stock_code='{c}' AND date='{dt}'
                """)
            conn.execute("COMMIT")
            updated += 1
        
        if (i + 1) % 100 == 0:
            elapsed = (datetime.now() - t0).seconds
            print(f"   进度: {i+1}/{len(stock_list)}  已处理: {updated}  耗时: {elapsed}s")
    
    print(f"   完成! 调整了 {updated} 只股票的价格")
    
    # ===== 5. 重新计算 change_pct =====
    print(f"\n4️⃣ 重新计算涨跌幅 (change_pct)...")
    
    conn.execute("""
        UPDATE stock_daily SET change_pct = ROUND(
            (close / NULLIF(LAG(close) OVER (PARTITION BY stock_code ORDER BY date), 0) - 1) * 100, 2
        )
    """)
    
    # ===== 6. 验证 =====
    print(f"\n{'='*60}")
    print(f"📊 验证英维克前复权效果:")
    
    yw = conn.execute("""
        SELECT date, open, close, change_pct 
        FROM stock_daily WHERE stock_code='002837' 
        AND date >= '2026-05-29' AND date <= '2026-06-02'
        ORDER BY date
    """).fetchall()
    
    for r in yw:
        print(f"   {r[0]} 开{r[1]:.2f} 收{r[2]:.2f} 涨跌{r[3]:+.2f}%")
    
    # MA计算
    ma = conn.execute("""
        WITH prices_asc AS (
            SELECT close FROM stock_daily 
            WHERE stock_code='002837' ORDER BY date
        )
        SELECT 
            (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 1) as cur,
            (SELECT AVG(close) FROM (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 5)) as m5,
            (SELECT AVG(close) FROM (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 20)) as m20,
            (SELECT AVG(close) FROM (SELECT close FROM prices_asc ORDER BY date DESC LIMIT 60)) as m60
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
