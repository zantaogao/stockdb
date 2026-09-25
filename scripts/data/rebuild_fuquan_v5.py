#!/usr/bin/env python3
"""
前复权重建 v5 — 新浪源, 支持正确列名映射
"""
import sys, time, json, numpy as np
from pathlib import Path
from datetime import datetime, date
import duckdb
import pandas as pd
import akshare as ak

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'

CODE_PREFIX = {
    '6': 'sh', '9': 'sh', '5': 'sh',
    '0': 'sz', '3': 'sz', '2': 'sz',
    '4': 'bj', '8': 'bj',
}

def sina_symbol(code):
    pf = CODE_PREFIX.get(code[0], 'sh')
    return f'{pf}{code}'

def fetch_adjusted_sina(code):
    """用新浪源获取前复权数据"""
    symbol = sina_symbol(code)
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_daily(symbol=symbol, adjust='qfq')
            if df is not None and not df.empty:
                # 处理列名映射
                df = df.rename(columns={
                    'date': 'date',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'volume': 'volume',
                    'amount': 'amount',
                    'turnover': 'turn_rate',
                })
                df['stock_code'] = code
                # 计算change_pct
                closes = df['close'].values
                chg = np.zeros(len(closes))
                chg[1:] = (closes[1:] / closes[:-1] - 1) * 100
                df['change_pct'] = chg
                # 振幅 = 没有，设为0
                df['amplitude'] = 0.0
                return df
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
    return None

def main():
    t0 = datetime.now()
    conn = duckdb.connect(str(DB_PATH))
    
    print(f"🔨 前复权重建 v5 — 新浪源")
    print(f"   时间: {t0.strftime('%Y-%m-%d %H:%M')}")
    
    # 恢复备份
    cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    if cnt == 0:
        print("\n1️⃣ 从备份恢复...")
        conn.execute("INSERT INTO stock_daily SELECT * FROM stock_daily_bak_pre_fuquan")
        conn.commit()
        cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
        print(f"   ✅ 已恢复 {cnt} 行")
    else:
        print(f"\n1️⃣ stock_daily 已有 {cnt} 行")
    
    # 检测除权股
    print(f"\n2️⃣ 检测除权跳空...")
    div_codes = [r[0] for r in conn.execute("""
        SELECT DISTINCT stock_code FROM (
            SELECT stock_code, date, open,
                   LAG(close) OVER (PARTITION BY stock_code ORDER BY date) as pc,
                   (open / NULLIF(LAG(close) OVER (PARTITION BY stock_code ORDER BY date), 0) - 1) * 100 as gp
            FROM stock_daily
        ) sub WHERE gp < -8 AND date >= '2026-01-01'
    """).fetchall()]
    print(f"   {len(div_codes)} 只需更新")
    
    if not div_codes:
        print("   ✅ 无需处理!")
        conn.close()
        return
    
    # 拉取+更新
    print(f"\n3️⃣ 拉取前复权数据 (每请求0.3s)...")
    updated = 0
    failed = []
    
    for i, code in enumerate(div_codes):
        df = fetch_adjusted_sina(code)
        
        if df is not None and not df.empty:
            keep_cols = ['stock_code', 'date', 'open', 'close', 'high', 'low',
                        'volume', 'amount', 'amplitude', 'change_pct', 'turn_rate']
            available = [c for c in keep_cols if c in df.columns]
            
            conn.execute(f"DELETE FROM stock_daily WHERE stock_code='{code}'")
            sub_df = df[available].copy()
            conn.execute("INSERT INTO stock_daily SELECT * FROM sub_df")
            conn.commit()
            updated += 1
        else:
            failed.append(code)
        
        if (i + 1) % 30 == 0 or i == len(div_codes) - 1:
            elapsed = (datetime.now() - t0).seconds
            rate = (i + 1) / max(elapsed, 1)
            eta = (len(div_codes) - i - 1) / max(rate, 0.1)
            print(f"   {i+1}/{len(div_codes)} ✅{updated} ❌{len(failed)} 耗时{elapsed}s ETA{eta:.0f}s")
        
        time.sleep(0.3)
    
    print(f"\n   完成! 更新{updated}只, 失败{len(failed)}")
    
    # 验证
    final_cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"📊 验证英维克:")
    
    yw = conn.execute("""
        SELECT date, open, close, change_pct FROM stock_daily 
        WHERE stock_code='002837' AND date>='2026-05-29' AND date<='2026-06-02'
        ORDER BY date
    """).fetchall()
    for r in yw:
        print(f"   {r[0]} 开{r[1]:.2f} 收{r[2]:.2f} 涨跌{r[3]:+.2f}%")
    
    ma = conn.execute("""
        WITH pa AS (SELECT close FROM stock_daily WHERE stock_code='002837' ORDER BY date)
        SELECT (SELECT close FROM pa ORDER BY date DESC LIMIT 1),
               (SELECT AVG(close) FROM (SELECT close FROM pa ORDER BY DATE DESC LIMIT 5)),
               (SELECT AVG(close) FROM (SELECT close FROM pa ORDER BY DATE DESC LIMIT 20)),
               (SELECT AVG(close) FROM (SELECT close FROM pa ORDER BY DATE DESC LIMIT 60))
    """).fetchall()
    if ma:
        cur, m5, m20, m60 = ma[0]
        dev60 = (cur/m60 - 1)*100
        print(f"\n   最新{cur:.2f} MA5={m5:.2f} MA20={m20:.2f} MA60={m60:.2f}")
        print(f"   dev_MA60={dev60:.2f}%")
        print(f"   清仓触发? {'✅会触发' if (m5<m20<m60) and dev60<-5 else '❌不触发'}")
        print(f"   均线空排? {'是' if m5<m20<m60 else '否'}")
    
    elapsed = (datetime.now() - t0).seconds
    print(f"\n⏱ 总耗时: {elapsed}s ({elapsed/60:.1f}min)")
    conn.close()

if __name__ == '__main__':
    main()
