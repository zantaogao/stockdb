#!/usr/bin/env python3
"""回填6月1日日线数据（Sina K线API）"""
import urllib.request, json, time, concurrent.futures, duckdb, sys, os
from datetime import date

DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock.db')

def sina_kline_code(code):
    if code in ('000001','399001','399006'):
        return {'000001':'sh000001','399001':'sz399001','399006':'sz399006'}[code]
    return f'sh{code}' if code.startswith(('6','68','9')) else f'sz{code}'

def fetch_one(code):
    """获取一只股票的6月1日日线"""
    try:
        sym = sina_kline_code(code)
        url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=10'
        req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
        resp = urllib.request.urlopen(req, timeout=10)
        klines = json.loads(resp.read())
        for k in klines:
            if k['day'].startswith('2026-06-01'):
                return (code, float(k['open']), float(k['high']), float(k['low']), 
                        float(k['close']), int(k['volume']))
    except:
        pass
    return None

def main():
    conn = duckdb.connect(DB_PATH)
    
    # 取6月2日有数据的股票（活跃股票）且6月1日缺失的
    codes = [r[0] for r in conn.execute("""
        SELECT DISTINCT a.stock_code FROM stock_daily a 
        WHERE a.date = '2026-06-02'
        AND a.stock_code NOT IN (SELECT stock_code FROM stock_daily WHERE date = '2026-06-01')
    """).fetchall()]
    
    print(f'需要回填: {len(codes)}只股票')
    
    # 删除之前可能存在的部分数据
    conn.execute("DELETE FROM stock_daily WHERE date = '2026-06-01'")
    
    inserted = 0
    batch = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_one, c): c for c in codes}
        done = 0
        for f in concurrent.futures.as_completed(futures):
            done += 1
            result = f.result()
            if result:
                code, op, hp, lp, cp, vol = result
                batch.append((code, date(2026,6,1), op, cp, hp, lp, vol))
                inserted += 1
            if done % 500 == 0:
                print(f'  进度: {done}/{len(codes)}, 已插入: {inserted}')
    
    # 批量写入
    if batch:
        print(f'写入 {len(batch)} 条到 stock_daily...')
        conn.executemany("""
            INSERT INTO stock_daily (stock_code, date, open, close, high, low, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, batch)
        conn.commit()
    
    # 验证
    r = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date='2026-06-01'").fetchone()
    print(f'\n✅ 完成! stock_daily 6月1日: {r[0]}条')
    conn.close()

if __name__ == '__main__':
    main()
