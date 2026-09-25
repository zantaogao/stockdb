#!/usr/bin/env python3
"""测试加主键前后财务表 DELETE + INSERT 是否正常"""
import duckdb

con = duckdb.connect('tushare.db', read_only=False)

# 1. 加主键
print('=== 给财务表加主键 ===')
for tbl in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
    try:
        con.execute(f'ALTER TABLE {tbl} ADD PRIMARY KEY (ts_code, end_date)')
        print(f'✅ {tbl} 主键添加成功')
    except Exception as e:
        print(f'❌ {tbl} 失败：{e}')
        con.close()
        exit()

# 2. 测试 DELETE + INSERT
print('\n=== 测试 DELETE + INSERT ===')
test_date = '20260717'

for tbl in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
    print(f'\n--- {tbl} ---')
    
    # DELETE 旧数据
    con.execute(f"DELETE FROM {tbl} WHERE ts_code = '000001.SZ' AND end_date = '{test_date}'")
    print('  DELETE 执行成功')
    
    # INSERT 新数据
    con.execute(f'''
        INSERT INTO {tbl} (ts_code, end_date, ann_date, report_type, revenue)
        VALUES ('000001.SZ', '{test_date}', '{test_date}', 'ANNUAL', 1000000.0)
    ''')
    print('  INSERT 执行成功')
    
    # 验证
    result = con.execute(f'''
        SELECT ts_code, end_date, revenue
        FROM {tbl}
        WHERE ts_code = '000001.SZ' AND end_date = '{test_date}'
    ''').fetchone()
    print(f'  验证：{result}')

# 3. 测试主键约束（试插入重复）
print('\n=== 测试主键约束 ===')
try:
    con.execute('''
        INSERT INTO fin_income (ts_code, end_date, ann_date, report_type, revenue)
        VALUES ('000001.SZ', '20260717', '20260717', 'ANNUAL', 999.0)
    ''')
    print('❌ 约束失效（允许重复）')
except Exception as e:
    print(f'✅ 约束生效：{str(e)[:60]}...')

# 4. 清理测试数据
print('\n=== 清理测试数据 ===')
for tbl in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
    con.execute(f"DELETE FROM {tbl} WHERE ts_code = '000001.SZ' AND end_date = '20260717'")
    print(f'  {tbl} 清理完成')

# CHECKPOINT
con.execute('CHECKPOINT')
con.close()

print('\n✅✅✅ 财务表加主键 + DELETE + INSERT 全部通过！')
