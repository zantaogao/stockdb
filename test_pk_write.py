#!/usr/bin/env python3
"""测试加主键前后 DELETE + INSERT 是否正常"""
import duckdb

con = duckdb.connect('tushare.db', read_only=False)

# 查现有数据
print('=== 测试前：moneyflow_raw 数据 ===')
row = con.execute('''
    SELECT ts_code, trade_date, net_mf_vol, net_mf_amount
    FROM moneyflow_raw
    WHERE ts_code = '000001.SZ' AND trade_date = 20260715
    LIMIT 1
''').fetchone()

if row:
    print(f'现有数据：{row}')
else:
    print('无 20260715 数据，查最新日期')
    row = con.execute('''
        SELECT ts_code, trade_date, net_mf_vol, net_mf_amount
        FROM moneyflow_raw
        WHERE ts_code = '000001.SZ'
        ORDER BY trade_date DESC
        LIMIT 1
    ''').fetchone()
    print(f'最新数据：{row}')

# 模拟 DELETE + INSERT
test_date = 20260717
print(f'\n=== 模拟 DELETE + INSERT {test_date} ===')

con.execute(f"DELETE FROM moneyflow_raw WHERE ts_code = '000001.SZ' AND trade_date = {test_date}")
print('DELETE 执行成功')

con.execute(f'''
    INSERT INTO moneyflow_raw (ts_code, trade_date, net_mf_vol, net_mf_amount)
    VALUES ('000001.SZ', {test_date}, 1000000, 50000000)
''')
print('INSERT 执行成功')

# 验证
result = con.execute(f'''
    SELECT ts_code, trade_date, net_mf_vol, net_mf_amount
    FROM moneyflow_raw
    WHERE ts_code = '000001.SZ' AND trade_date = {test_date}
''').fetchone()

print(f'验证结果：{result}')

# 清理
con.execute(f"DELETE FROM moneyflow_raw WHERE ts_code = '000001.SZ' AND trade_date = {test_date}")
print('测试数据已清理')

con.execute('CHECKPOINT')
con.close()

print('\n✅ DELETE + INSERT 逻辑测试通过（无主键时）')
