#!/usr/bin/env python3
"""
修复 stock_info 中的空字段：行业(industry)、总股本、市值等
使用 baostock 数据源（可靠、免费、稳定）
"""
import os, sys, time
from datetime import date

# 清除代理
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')
import duckdb
import baostock as bs
import pandas as pd

def fix_industry():
    """修复行业字段"""
    print("=" * 60)
    print(f"📋 修复 stock_info 行业字段 — {date.today()}")
    print("=" * 60)
    
    conn = duckdb.connect(DB)
    total = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
    empty = conn.execute("SELECT COUNT(*) FROM stock_info WHERE industry IS NULL OR industry=''").fetchone()[0]
    print(f"  总股票: {total}，空行业: {empty}")
    
    if empty == 0:
        print("  ✅ 行业字段已全部填充，无需修复")
        conn.close()
        return True
    
    # 1. 从 baostock 获取行业映射
    print("\n📥 从 baostock 获取行业分类...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"  ❌ baostock 登录失败: {lg.error_msg}")
        return False
    
    rs = bs.query_stock_industry()
    if rs.error_code != '0':
        print(f"  ❌ 查询失败: {rs.error_msg}")
        bs.logout()
        return False
    
    records = []
    while rs.next():
        records.append(rs.get_row_data())
    bs.logout()
    
    df = pd.DataFrame(records, columns=rs.fields)
    print(f"  ✅ baostock 返回 {len(df)} 条行业数据")
    
    # 2. 转换代码格式: sh.600000 → 600000
    df['stock_code'] = df['code'].str.replace('sh.', '').str.replace('sz.', '').str.replace('sz1', '').str.replace('bj.', '')
    # 只保留有行业的值
    df_valid = df[df['industry'].notna() & (df['industry'] != '')]
    
    # 3. 逐个更新
    updated = 0
    skipped = 0
    for _, row in df_valid.iterrows():
        code = row['stock_code']
        industry = row['industry']
        r = conn.execute("UPDATE stock_info SET industry=? WHERE stock_code=? AND (industry IS NULL OR industry='')", 
                         [industry, code])
        if r.fetchone()[0] > 0 or True:  # DuckDB UPDATE returns row count differently
            updated += 1
    
    # 用更直接的方式统计
    conn.execute("BEGIN TRANSACTION")
    for _, row in df_valid.iterrows():
        code = row['stock_code']
        industry = row['industry']
        conn.execute("UPDATE stock_info SET industry=? WHERE stock_code=?", [industry, code])
    conn.execute("COMMIT")
    
    # 4. 检查结果
    still_empty = conn.execute("SELECT COUNT(*) FROM stock_info WHERE industry IS NULL OR industry=''").fetchone()[0]
    filled = empty - still_empty
    print(f"\n  ✅ 已填充 {filled}/{empty} 只股票行业")
    if still_empty > 0:
        print(f"  ⚠️ 仍有 {still_empty} 只未填充（可能已退市或baostock无数据）")
    
    conn.close()
    return True

def fix_market_cap():
    """修复总市值/总股本/流通股本（从 stock_daily 最新日线反算）"""
    print("\n📋 修复市值/股本字段（从日线反算）...")
    
    conn = duckdb.connect(DB)
    
    # 检查现有数据
    for f in ['total_shares', 'float_shares', 'market_cap']:
        cnt = conn.execute(f"SELECT COUNT(*) FROM stock_info WHERE {f} IS NOT NULL AND {f} != 0").fetchone()[0]
        print(f"  {f}: {cnt}/5512 有值")
    
    # 看 stock_daily 是否有最近数据
    latest = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    print(f"  最新日线日期: {latest}")
    
    if not latest:
        print("  ❌ 无日线数据，跳过")
        return False
    
    # 获取股票市值信息 - 从日线最新收盘 × 总股本？
    # 但实际上总股本也没有，所以没办法直接计算
    # 先用 baostock 看看有没有总股本数据
    print("  ⚠️ 总股本/流通股本需从其他数据源获取，暂时跳过")
    conn.close()
    return False

def fix_list_date():
    """修复上市日期"""
    print("\n📋 修复上市日期...")
    conn = duckdb.connect(DB)
    
    # 从 baostock 获取
    lg = bs.login()
    if lg.error_code != '0':
        conn.close()
        return False
    
    rs = bs.query_stock_basic()
    if rs.error_code == '0':
        records = []
        while rs.next():
            records.append(rs.get_row_data())
        df = pd.DataFrame(records, columns=rs.fields)
        # 只保留股票（type=1），排除指数
        df_stock = df[df['type'] == '1'].copy()
        df_stock['stock_code'] = df_stock['code'].str.replace('sh.', '').str.replace('sz.', '').str.replace('bj.', '')
        
        updated = 0
        for _, row in df_stock.iterrows():
            code = row['stock_code']
            ipo_date = row.get('ipoDate', '')
            if ipo_date:
                conn.execute("UPDATE stock_info SET list_date=? WHERE stock_code=?", [ipo_date, code])
                updated += 1
        print(f"  ✅ 已更新 {updated} 只股票上市日期")
    
    bs.logout()
    conn.close()
    return True

def main():
    success = fix_industry()
    if success:
        fix_list_date()
    fix_market_cap()
    
    # 最终检查
    print("\n" + "=" * 60)
    print("📊 最终检查")
    conn = duckdb.connect(DB)
    for f in ['industry', 'board', 'market', 'list_date']:
        if f in ['industry']:
            empty = conn.execute(f"SELECT COUNT(*) FROM stock_info WHERE {f} IS NULL OR CAST({f} AS VARCHAR)=''").fetchone()[0]
        else:
            notnull = conn.execute(f"SELECT COUNT(*) FROM stock_info WHERE {f} IS NOT NULL").fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
            print(f"  {f}: {notnull}/{total} 有值")
            continue
        total = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
        print(f"  {f}: {total-empty}/{total} 有值, {empty} 空")
    conn.close()
    print("=" * 60)

if __name__ == '__main__':
    main()
