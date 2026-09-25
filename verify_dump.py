import duckdb

# 1. 源DB行数
conn = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db')
tables = conn.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
).fetchall()

src_counts = {}
for t in tables:
    cnt = conn.execute('SELECT COUNT(*) FROM ' + t[0]).fetchone()[0]
    src_counts[t[0]] = cnt

src_total = sum(src_counts.values())
conn.close()

# 2. 验证SQL文件结构
with open('/Users/zantao/.hermes/stockdb/tushare_dump.sql', 'r') as f:
    header = f.read(200)

print('=== SQL Header ===')
print(header[:300])

# 3. 检查SQL文件中是否有所有表的CREATE TABLE
import re
with open('/Users/zantao/.hermes/stockdb/tushare_dump.sql', 'r') as f:
    content = f.read()

# 找所有CREATE TABLE
creates = re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', content)
print('\n=== CREATE TABLEs (%d) ===' % len(creates))
for c in sorted(creates):
    print('  ' + c)

# 找所有INSERT
inserts = re.findall(r'INSERT INTO (\w+)', content)
print('\n=== INSERT INTOs (%d) ===' % len(inserts))
for i in sorted(set(inserts)):
    print('  ' + i)

# 4. 检查最后一行INSERT是否正确闭合
lines = content.split('\n')
last_line = lines[-1].strip()
print('\n=== Last line ===')
print(last_line[:200] + '...' if len(last_line) > 200 else last_line)
print('Ends with semicolon:', last_line.endswith(';'))

# 5. 统计INSERT语句行数
insert_lines = [l for l in lines if l.startswith('INSERT')]
print('\n=== Total INSERT statements: %d ===' % len(insert_lines))

# 6. 检查stk_factor是否有数据（最大表）
stk_factor_inserts = [l for l in lines if 'stk_factor' in l]
print('=== stk_factor INSERT statements: %d ===' % len(stk_factor_inserts))
if stk_factor_inserts:
    print('First:', stk_factor_inserts[0][:150])
    print('Last:', stk_factor_inserts[-1][:150])

# 7. 检查daily表的最新日期
daily_inserts = [l for l in lines if 'daily' in l]
if daily_inserts:
    last_daily = daily_inserts[-1]
    dates = re.findall(r"'(\d{8})'", last_daily)
    print('\n=== Last daily date sample: %s ===' % (dates[-5:] if dates else 'none'))

# 8. 文件总大小
import os
size_mb = os.path.getsize('/Users/zantao/.hermes/stockdb/tushare_dump.sql') / 1024 / 1024
print('\n=== File size: %.1f MB ===' % size_mb)

# 9. 打印源DB各表行数汇总
print('\n=== Source DB Row Counts ===')
for k, v in sorted(src_counts.items()):
    print('%-25s %12s' % (k, '{:,}'.format(v)))
print('%-25s %12s' % ('total', '{:,}'.format(src_total)))

# 10. 验证导入：用DuckDB导入SQL
print('\n=== Verifying import ===')
verify_conn = duckdb.connect(':memory:')
with open('/Users/zantao/.hermes/stockdb/tushare_dump.sql', 'r') as f:
    verify_conn.execute(f.read())
# 检查导入后的表
vtables = verify_conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()
print('Imported tables: %d' % len(vtables))
for v in vtables[:5]:
    cnt = verify_conn.execute('SELECT COUNT(*) FROM ' + v[0]).fetchone()[0]
    print('  %-25s %12s' % (v[0], '{:,}'.format(cnt)))
print('  ...')
verify_conn.close()
print('\nImport verification PASSED')
