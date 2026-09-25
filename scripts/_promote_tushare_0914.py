#!/usr/bin/env python3
"""促升 tushare.db.new → tushare.db（09-14 看门狗误杀后的补救，用户拍板方案A）
逻辑复刻 update_tushare_api.py 步骤5/6：等写锁→CHECKPOINT→全表强读→os.replace→复验
"""
import duckdb, os, sys, time, subprocess
from pathlib import Path

SD = Path(os.path.expanduser("~/.hermes/stockdb"))
MAIN, TEMP = SD/"tushare.db", SD/"tushare.db.new"

def main_pid_alive():
    out = subprocess.run(["pgrep", "-f", "update_etf.py"], capture_output=True, text=True).stdout.strip()
    return out != ""

# 1. 等 update_etf 写完（主库锁释放）
for i in range(60):
    if not main_pid_alive():
        print(f"[promote] update_etf 已退出，等待{i*30}s后开始")
        break
    print(f"[promote] update_etf 仍在跑 (pid={subprocess.run(['pgrep','-f','update_etf.py'],capture_output=True,text=True).stdout.strip()})，30s后重查")
    time.sleep(30)
else:
    sys.exit("[promote] 等30分钟仍未释放，放弃促升留给人工")

# 确认主库无进程占用
out = subprocess.run(["lsof", "-t", str(MAIN)], capture_output=True, text=True).stdout.strip()
if out:
    sys.exit(f"[promote] 主库仍被占用: pid={out}，放弃")

# 2. 临时库 CHECKPOINT + WAL 检查
vc = duckdb.connect(str(TEMP), read_only=False)
vc.execute("CHECKPOINT")
vc.close()
wal = str(TEMP)+".wal"
if os.path.exists(wal) and os.path.getsize(wal) > 0:
    sys.exit(f"[promote] WAL未清空 {os.path.getsize(wal)}B，放弃")

# 3. 全表强读校验（复刻步骤5.1）
vc = duckdb.connect(str(TEMP), read_only=True)
vtables = vc.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name").fetchall()
total = 0
for (vt,) in vtables:
    cur = vc.cursor()
    cur.execute(f'SELECT * FROM "{vt}"')
    cnt = 0
    while True:
        batch = cur.fetchmany(50000)
        if not batch: break
        cnt += len(batch)
    cur.close()
    total += cnt
    print(f"  {vt}: {cnt:,} rows OK", flush=True)
vc.close()
print(f"[promote] 校验通过 {len(vtables)}表 {total:,}行", flush=True)

# 4. 原子交换 + 复验
os.replace(str(TEMP), str(MAIN))
print("[promote] os.replace 完成，复验新主库...", flush=True)
vc = duckdb.connect(str(MAIN), read_only=True)
n = vc.execute("select count(*) from stock_daily where date='2026-09-14'").fetchone()[0]
mx = vc.execute("select max(date) from stock_daily").fetchone()[0]
vc.close()
assert n == 5550, f"复验失败: 0914行数={n}"
print(f"[promote] ✅ 促升成功: stock_daily max={mx}, 09-14 {n}行", flush=True)
