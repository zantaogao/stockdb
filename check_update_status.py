#!/usr/bin/env python3
"""
检查 tushare 更新状态
- 检查各表最新日期
- 检查主键冲突
- 检查数据库完整性
"""
import duckdb
from datetime import datetime, timedelta

DB = '~/.hermes/stockdb/tushare.db'

def check():
    con = duckdb.connect(str(DB), read_only=True)
    
    print('=' * 60)
    print(f'检查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)
    
    # 1. 检查各表最新日期
    print('\n【各表最新日期】')
    tables_to_check = [
        ('daily', 'trade_date', '日线'),
        ('moneyflow_raw', 'trade_date', '资金流向'),
        ('stk_factor_pro', 'trade_date', '因子数据'),
        ('fin_income', 'end_date', '利润表'),
        ('fin_balancesheet', 'end_date', '资产负债表'),
        ('fin_cashflow', 'end_date', '现金流量表'),
    ]
    
    today = datetime.now().strftime('%Y%m%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    for tbl, date_col, desc in tables_to_check:
        try:
            latest = con.execute(f"SELECT MAX({date_col}) FROM {tbl}").fetchone()[0]
            if latest:
                status = '✅' if str(latest) >= yesterday else '⚠️'
                print(f'{status} {tbl:<20} ({desc:<8}) latest={latest}')
            else:
                print(f'⚠️ {tbl:<20} ({desc:<8}) 无数据')
        except Exception as e:
            print(f'❌ {tbl:<20} ({desc:<8}) ERROR: {e}')
    
    # 2. 检查主键冲突（理论上不应该有）
    print('\n【主键冲突检查】')
    pk_tables = [
        ('fin_income', 'ts_code, end_date'),
        ('fin_balancesheet', 'ts_code, end_date'),
        ('fin_cashflow', 'ts_code, end_date'),
    ]
    
    conflict_found = False
    for tbl, pk_cols in pk_tables:
        try:
            dup = con.execute(f'''
                SELECT COUNT(*) - COUNT(DISTINCT ({pk_cols})) as dup_count
                FROM {tbl}
            ''').fetchone()[0]
            if dup > 0:
                print(f'❌ {tbl}: 发现 {dup} 条重复主键！')
                conflict_found = True
            else:
                print(f'✅ {tbl}: 无重复')
        except Exception as e:
            print(f'⚠️ {tbl}: 检查失败 {e}')
    
    if not conflict_found:
        print('✅ 所有表主键正常')
    
    # 3. 检查 WAL 文件
    print('\n【WAL 状态】')
    import os
    wal_file = str(DB) + '.wal'
    shm_file = str(DB) + '.shm'
    
    if os.path.exists(wal_file):
        wal_size = os.path.getsize(wal_file) / 1024 / 1024
        print(f'⚠️ WAL 文件存在：{wal_size:.2f} MB')
    else:
        print('✅ WAL 文件已清理')
    
    if os.path.exists(shm_file):
        shm_size = os.path.getsize(shm_file) / 1024 / 1024
        print(f'⚠️ SHM 文件存在：{shm_size:.2f} MB')
    else:
        print('✅ SHM 文件已清理')
    
    # 4. 数据库完整性
    print('\n【数据库完整性】')
    try:
        result = con.execute('PRAGMA integrity_check').fetchone()[0]
        if result == 'ok':
            print('✅ 数据库完整')
        else:
            print(f'❌ 数据库异常: {result[:100]}')
    except Exception as e:
        print(f'❌ 完整性检查失败: {e}')
    
    con.close()
    
    print('\n' + '=' * 60)
    if conflict_found:
        print('⚠️ 发现主键冲突，检查 update_tushare_api.py 日志')
    else:
        print('✅ 更新完成，状态正常')
    print('=' * 60)

if __name__ == '__main__':
    check()
