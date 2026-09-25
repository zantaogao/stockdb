#!/usr/bin/env python3
"""
导入广发易淘金导出的资金流数据到money_flow表
用法: python3 import_gf_money_flow.py <导出的数据文件.csv>

支持格式：
  CSV: 日期,股票代码,股票名称,主力净流入,散户净流入,主力净占比,...
  Excel: 同上
  
数据会写入 ~/.hermes/stockdb/stock.db 的 money_flow 表
"""
import os, sys, csv, duckdb
from datetime import datetime

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def parse_file(filepath):
    """
    TODO: 根据易淘金实际导出格式修改解析逻辑
    当前为占位实现，假设CSV格式为：
    日期,代码,名称,主力净流入(元),散户净流入(元),主力净占比(%)
    """
    records = []
    with open(filepath, 'r', encoding='gbk') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        print(f"文件头: {header}")
        
        for row in reader:
            if len(row) < 5:
                continue
            try:
                date_str = row[0].strip()
                # 尝试多种日期格式
                for fmt in ['%Y/%m/%d', '%Y-%m-%d', '%Y%m%d', '%Y.%m.%d']:
                    try:
                        dt = datetime.strptime(date_str, fmt).date()
                        break
                    except:
                        continue
                else:
                    print(f"  跳过无法解析的日期: {date_str}")
                    continue
                
                code = row[1].strip().zfill(6)
                main_net = float(row[3]) if row[3] else 0
                retail_net = float(row[4]) if row[4] else 0
                main_pct = float(row[5]) / 100.0 if len(row) > 5 and row[5] else 0
                
                records.append((code, dt, main_net, retail_net, main_pct))
            except (ValueError, IndexError) as e:
                continue
    
    return records

def import_to_db(records):
    """写入money_flow表"""
    if not records:
        print("没有有效数据")
        return
    
    conn = duckdb.connect(DB)
    try:
        conn.execute("BEGIN TRANSACTION")
        inserted = 0
        for code, dt, main_net, retail_net, main_pct in records:
            conn.execute(
                "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                [code, dt, main_net, retail_net, main_pct],
            )
            inserted += 1
        conn.execute("COMMIT")
        print(f"✅ 成功导入 {inserted} 条资金流记录")
        # 统计
        r = conn.execute("""
            SELECT COUNT(DISTINCT stock_code), COUNT(DISTINCT date), 
                   MIN(date), MAX(date) FROM money_flow
        """).fetchone()
        print(f"  当前money_flow: {r[0]}只股票, {r[1]}个交易日, {r[2]}~{r[3]}")
    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"❌ 导入失败: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 import_gf_money_flow.py <数据文件>")
        sys.exit(1)
    
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        sys.exit(1)
    
    print(f"解析文件: {filepath}")
    records = parse_file(filepath)
    print(f"解析到 {len(records)} 条记录")
    
    if records:
        print(f"  样例: {records[0]}")
        ans = input("确认导入? (y/n): ")
        if ans.lower() == 'y':
            import_to_db(records)
        else:
            print("已取消")
