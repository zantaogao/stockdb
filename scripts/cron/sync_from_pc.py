#!/usr/bin/env python3
"""
从 PC 同步 TDX 数据到本地 stock.db
PC: pumma@192.168.3.168 C:/Users/zanta/tdx_stock_data.db
本地: ~/.hermes/stockdb/stock.db
每天自动增量同步日K数据，覆盖已有日期
"""
import subprocess, sys, json, time
from pathlib import Path
from datetime import datetime, timedelta
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
STOCK_DB = str(BASE / 'stock.db')

PC_SCRIPT = r'''
import sqlite3, json, sys
DB = r'C:\Users\zanta\tdx_stock_data.db'
c = sqlite3.connect(DB).cursor()
mode = sys.argv[1]
if mode == 'latest':
    c.execute('SELECT MAX(date) FROM daily')
    r = c.fetchone()[0]
    print(r) if r else None
elif mode == 'daily':
    since = sys.argv[2]
    limit = sys.argv[3] if len(sys.argv) > 3 else ''
    where = 'date >= "' + since + '"'
    if limit:
        where += ' AND date <= "' + limit + '"'
    c.execute('SELECT code, date, open, high, low, close, volume, amount FROM daily WHERE ' + where + ' ORDER BY code, date')
    rows = c.fetchall()
    data = [{'code':r[0],'date':r[1],'open':r[2],'high':r[3],'low':r[4],'close':r[5],'volume':r[6],'amount':r[7]} for r in rows]
    json.dump(data, sys.stdout)
elif mode == 'names':
    c.execute('SELECT code, name FROM stocks WHERE name != ""')
    rows = c.fetchall()
    data = [{'code':r[0],'name':r[1]} for r in rows]
    json.dump(data, sys.stdout)
c.close()
'''

def run_ssh(mode, *args):
    """在 PC 上运行 Python 脚本（先 scp 传文件再 ssh 执行）"""
    script_path = str(Path(__file__).parent / '_tdx_query.py')
    with open(script_path, 'w') as f:
        f.write(PC_SCRIPT)
    
    try:
        # 第一步：SCP 传脚本到 PC
        subprocess.run(
            ['scp', script_path, 'pumma@192.168.3.168:C:/Users/zanta/tdx_query.py'],
            capture_output=True, text=True, timeout=30
        )
        # 第二步：SSH 执行
        extra = ' '.join(args)
        cmd = f'python C:/Users/zanta/tdx_query.py {mode} {extra}'
        result = subprocess.run(
            ['ssh', 'pumma@192.168.3.168', 'cmd /c', cmd],
            capture_output=True, text=True, timeout=300
        )
        return result.stdout.strip(), result.returncode
    finally:
        Path(script_path).unlink(missing_ok=True)

def get_latest_date():
    """获取 PC 上最新交易日"""
    out, rc = run_ssh("latest")
    return out if out else None
def get_latest_local_date():
    """获取本地最新交易日"""
    import duckdb
    conn = duckdb.connect(STOCK_DB)
    row = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    conn.close()
    d = row[0]
    if not d:
        return None
    if isinstance(d, str):
        return d
    return d.strftime('%Y-%m-%d')

def sync_daily_data(since_date, limit_date=None):
    """从 PC 拉取日K数据并写入本地"""
    print(f"从 PC 拉取日K数据: {since_date} ~ {limit_date or '最新'}")

    args = ["daily", since_date]
    if limit_date:
        args.append(limit_date)

    out, rc = run_ssh(*args)
    if rc != 0 or not out:
        print("ERROR: 从 PC 拉取数据失败", file=sys.stderr)
        return 0

    data = json.loads(out)
    if not data:
        print("没有新数据")
        return 0

    print(f"拉取到 {len(data)} 条数据，写入本地...")

    conn = duckdb.connect(STOCK_DB)

    # 删除已有日期的数据（覆盖模式）
    dates = list(set(r['date'] for r in data))
    formatted_dates = [f"'{d[0:4]}-{d[4:6]}-{d[6:8]}'" for d in dates]
    delete_sql = f"DELETE FROM stock_daily WHERE date IN ({', '.join(formatted_dates)})"
    conn.execute(delete_sql)

    # 批量插入
    insert_sql = """
        INSERT INTO stock_daily (stock_code, date, open, high, low, close, volume, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for r in data:
        d = r['date']
        date_fmt = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        code = r['code'].zfill(6)
        rows_to_insert.append((
            code, date_fmt,
            r.get('open'), r.get('high'), r.get('low'), r.get('close'),
            r.get('volume'), r.get('amount'),
        ))

    conn.executemany(insert_sql, rows_to_insert)

    # 同步股票名称
    print("同步股票名称...")
    out, rc = run_ssh("names")
    if rc == 0 and out:
        names = json.loads(out)
        for n in names:
            code = n['code'].zfill(6)
            name = n['name']
            if name:
                conn.execute(
                    "UPDATE stock_daily SET stock_name = ? WHERE stock_code = ? AND (stock_name IS NULL OR stock_name = '') LIMIT 1",
                    (name, code)
                )

    conn.commit()
    conn.close()
    return len(rows_to_insert)

def main():
    pc_latest = get_latest_date()
    local_latest = get_latest_local_date()

    print(f"PC 最新日期: {pc_latest}")
    print(f"本地最新日期: {local_latest}")

    if not pc_latest:
        print("无法获取 PC 最新日期", file=sys.stderr)
        sys.exit(1)

    pc_date = datetime.strptime(pc_latest, '%Y%m%d')

    if local_latest:
        local_date = datetime.strptime(local_latest, '%Y-%m-%d')
        if pc_date <= local_date:
            print("本地数据已经是最新的，无需同步")
            return
        since = (local_date + timedelta(days=1)).strftime('%Y%m%d')
    else:
        since = '20150101'

    count = sync_daily_data(since_date=since)
    print(f"同步完成: {count} 条日K数据")

if __name__ == '__main__':
    main()
