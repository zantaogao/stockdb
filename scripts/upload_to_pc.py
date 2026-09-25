#!/usr/bin/env python3
"""上传因子库到PC并远程执行"""
import paramiko, os

PC = '192.168.3.168'
USER = 'pumma'
PASS = 'tao62244'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PC, username=USER, password=PASS, timeout=10)

# 创建目录
c.exec_command('cmd /c mkdir C:\\Users\\pumma\\factor_lib')
c.exec_command('cmd /c mkdir C:\\Users\\pumma\\factor_lib\\scripts')

# 上传脚本
sftp = c.open_sftp()
local = os.path.expanduser('~/.hermes/stockdb/scripts/factor_library.py')
remote = 'C:/Users/pumma/factor_lib/scripts/factor_library.py'
sftp.put(local, remote)
sftp.close()
print('脚本上传完成')

# 上传数据库（只上传1年数据范围，压缩小很多）
# 先看看数据库多大
db_size = os.path.getsize(os.path.expanduser('~/.hermes/stockdb/stock.db'))
print(f'数据库大小: {db_size/1024/1024:.0f}MB')

c.close()
