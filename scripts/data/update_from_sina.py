#!/usr/bin/env python3
"""
新浪数据源增量更新脚本 — 替代 EastMoney 方案
"""
import os, sys, urllib.request, json
from datetime import date, datetime

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')
import duckdb

def get_stock_codes(conn):
    codes = conn.execute("SELECT stock_code FROM stock_info").fetchdf()
    return codes['stock_code'].tolist()

def batch_fetch_sina(codes_batch):
    symbols = []
    for code in codes_batch:
        if code.startswith("3") or code.startswith("0"):
            symbols.append(f"sz{code}")
        elif code.startswith("8") or code.startswith("4"):
            symbols.append(f"bj{code}")
        else:
            symbols.append(f"sh{code}")
    
    url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=20).read()
    text = raw.decode('gbk')
    
    results = []
    for line in text.strip().split('\n'):
        if 'hq_str_' not in line:
            continue
        try:
            data = line.split('"')[1].split(',')
            code_from = line.split('hq_str_')[1].split('=')[0][2:]
            if len(data) >= 33 and data[1] and float(data[2]) > 0:
                open_p = float(data[1])
                prev_close = float(data[2])
                close_p = float(data[3])
                high_p = float(data[4])
                low_p = float(data[5])
                volume_shares = int(float(data[8]))          # 成交股数
                # 转成手(handred shares)保持与旧数据一致
                vol_handred = volume_shares // 100
                amount_yuan = float(data[9])                 # 成交额(元)
                change_pct = round((close_p - prev_close) / prev_close * 100, 2)
                amplitude = round((high_p - low_p) / prev_close * 100, 2)
                # 流通股从stock_info获取换手率在主流程计算
                results.append((
                    code_from, open_p, close_p,
                    high_p, low_p,
                    vol_handred, amount_yuan,
                    amplitude, change_pct
                ))
        except:
            pass
    return results

def main():
    today = date.today().isoformat()
    print(f"📅 新浪增量更新 — {today} {datetime.now().strftime('%H:%M')}")
    
    conn = duckdb.connect(DB)
    codes = get_stock_codes(conn)
    print(f"📊 共 {len(codes)} 只股票")
    
    batch_size = 50
    batches = [codes[i:i+batch_size] for i in range(0, len(codes), batch_size)]
    print(f"🔗 分 {len(batches)} 批请求新浪 API")
    
    all_rows = []
    failed = 0
    
    for i, batch in enumerate(batches):
        try:
            rows = batch_fetch_sina(batch)
            all_rows.extend(rows)
        except Exception as e:
            failed += len(batch)
        
        if (i+1) % 10 == 0:
            print(f"  → {i+1}/{len(batches)}批: {len(all_rows)}条成功, {failed}条失败")
    
    print(f"\n📝 共获取 {len(all_rows)} 条数据")
    
    if all_rows:
        # Pre-load float_shares for turn_rate computation
        shares_info = {}
        for row in conn.execute("SELECT stock_code, float_shares FROM stock_info").fetchall():
            shares_info[row[0]] = row[1] or 0

        conn.execute("BEGIN TRANSACTION")
        # Delete today's data first
        conn.execute(f"DELETE FROM stock_daily WHERE date = '{today}'")
        # Insert new data
        for r in all_rows:
            try:
                code, op, cp, hp, lp, vol, amt, amp, chg = r
                tr = round(vol / shares_info.get(code, 1) * 100, 2) if shares_info.get(code, 0) > 0 else 0
                conn.execute(f"""
                    INSERT INTO stock_daily (stock_code, date, open, close, high, low, volume, amount, amplitude, change_pct, turn_rate)
                    VALUES ('{code}', '{today}', {op}, {cp}, {hp}, {lp}, 
                            {vol}, {amt}, {amp}, {chg}, {tr})
                """)
            except:
                pass
        conn.execute("COMMIT")
        
        actual = conn.execute(f"SELECT COUNT(*) FROM stock_daily WHERE date='{today}'").fetchone()[0]
        print(f"✅ 写入完成: {actual} 条")
    
    conn.close()
    print("✅ 更新完成")

if __name__ == '__main__':
    main()
