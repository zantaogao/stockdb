#!/usr/bin/env python3
"""
修复 5/25~6/4 问题日线数据 — v2
根因：backfill_jun1.py等脚本把Sina K线API的k['volume'](股)直接存到DB volume列(应存手)
修复：重新抓取，正确映射
"""
import sys, json, time, concurrent.futures, duckdb, urllib.request
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path.home() / '.hermes' / 'stockdb' / 'stock.db'
FIX_DATES = ['2026-05-25','2026-05-26','2026-05-27','2026-05-28',
             '2026-06-01','2026-06-02','2026-06-03','2026-06-04']

def sina_symbol(code):
    if code in ('000001','399001','399006'):
        return {'000001':'sh000001','399001':'sz399001','399006':'sz399006'}[code]
    return f'sh{code}' if code.startswith(('6','68','9')) else f'sz{code}'

def fetch_one(code, fix_date):
    """获取单只股票的K线数据，正确映射字段"""
    try:
        sym = sina_symbol(code)
        url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=30'
        req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
        resp = urllib.request.urlopen(req, timeout=10)
        klines = json.loads(resp.read())
        for k in klines:
            if k['day'].startswith(fix_date):
                op = float(k['open'])
                hp = float(k['high'])
                lp = float(k['low'])
                cp = float(k['close'])
                vol_shares = int(k['volume'])     # K线volume = 股
                vol_handred = max(1, vol_shares // 100)  # → 手
                avg_price = (hp + lp + cp) / 3
                amt = round(vol_shares * avg_price, 2)  # 成交额(元)
                amp = round((hp - lp) / op * 100, 2) if op > 0 else 0
                chg = round((cp - op) / op * 100, 2) if op > 0 else 0
                return (code, date.fromisoformat(fix_date),
                        op, cp, hp, lp, vol_handred, amt, amp, chg, None)
        return None
    except Exception as e:
        # 只记录错误不中断
        print(f'    ⚠️ {code}: {type(e).__name__}')
        return None

def main():
    conn = duckdb.connect(str(DB_PATH))
    
    for fix_date in FIX_DATES:
        # 获取该日期有数据的股票代码（从相邻日期取）
        adj_date = '2026-06-05' if fix_date < '2026-06-05' else '2026-06-04'
        codes = [r[0] for r in conn.execute(f"""
            SELECT DISTINCT stock_code FROM stock_daily WHERE date='{adj_date}'
        """).fetchall()]
        
        print(f'\n📅 {fix_date}: 修复 {len(codes)} 只...')
        
        # 删除旧数据
        conn.execute(f"DELETE FROM stock_daily WHERE date='{fix_date}'")
        
        batch = []
        done = 0
        errors = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_one, c, fix_date): c for c in codes}
            for f in concurrent.futures.as_completed(futures):
                done += 1
                result = f.result()
                if result:
                    batch.append(result)
                else:
                    errors += 1
                if done % 1000 == 0:
                    print(f'    进度: {done}/{len(codes)} 成功: {len(batch)} 失败: {errors}')
                time.sleep(0.02)
        
        if batch:
            print(f'  📝 写入 {len(batch)} 条...')
            conn.executemany("""
                INSERT INTO stock_daily (stock_code, date, open, close, high, low, volume, amount, amplitude, change_pct, turn_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()
        else:
            print(f'  ❌ 无数据写入！')
        
        r = conn.execute(f"SELECT COUNT(*) FROM stock_daily WHERE date='{fix_date}'").fetchone()[0]
        print(f'  ✅ {fix_date}: {r} 条, 失败: {errors}')
    
    # 验证
    print('\n' + '='*50)
    print('📊 修复后验证')
    for d in FIX_DATES + ['2026-06-05', '2026-06-08']:
        r = conn.execute(f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN amount IS NOT NULL AND volume > 0 
                            AND ABS(amount / (close * volume) - 100) > 20 THEN 1 ELSE 0 END)
            FROM stock_daily WHERE date='{d}'
        """).fetchone()
        if r[0] > 0:
            print(f'  {d}  cnt={r[0]:>5}  amt_null={r[1]:>5}  unit_wrong={r[2]:>5}')
        else:
            print(f'  {d}  ❌ 无数据')
    
    conn.close()
    print(f'\n🏁 完成')

if __name__ == '__main__':
    main()
