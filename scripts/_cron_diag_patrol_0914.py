#!/usr/bin/env python3
"""只读诊断：复现 patrol_check.py 的 ❌ OperationalError('unable to open database file')。

背景: 22:00 补拉链尾部 patrol stk_factor 偶发 ❌（09-03/07/10/11/14 均出现），
重跑即 ✅。本脚本在 /tmp 副本上做受控实验，判定是哪一种"打不开"：
  A) 有写者持未提交写事务时，mode=ro 连接 signals.db
  B) 写者被强杀后残留非空 -wal（模拟异常退出/失败回滚）
  C) 残留非空 -wal 且 -shm 不存在（无写者协调）
  D) duckdb read_only 在文件缺失 / 被独占锁时的报错形态（排除 duckdb 侧）
禁止写真实库：全部实验对象都是 /tmp 下的副本。
"""
import os, shutil, signal, sqlite3, subprocess, sys, time

TMP = "/tmp/patrolprobe"
SRC = os.path.expanduser("~/.hermes/stockdb/signals.db")
print("python:", sys.executable, sys.version.split()[0])
print("HOME env:", os.environ.get("HOME"), "| expanduser(~) =", os.path.expanduser("~"))
try:
    import duckdb
    print("duckdb:", duckdb.__version__)
except Exception as e:
    print("duckdb import FAIL:", repr(e))

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)


def db_ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)


def try_ro(p, tag):
    try:
        c = db_ro(p)
        v = c.execute("SELECT count(*) FROM new_factors").fetchone()[0]
        c.close()
        print(f"  [{tag}] mode=ro OK (new_factors={v})")
    except Exception as e:
        print(f"  [{tag}] mode=ro FAIL -> {type(e).__module__}.{type(e).__name__}{e.args!r}")


def try_duck(p, tag):
    try:
        c = duckdb.connect(p, read_only=True)
        c.execute("SELECT 1").fetchone()
        c.close()
        print(f"  [{tag}] duckdb ro OK")
    except Exception as e:
        print(f"  [{tag}] duckdb ro FAIL -> {type(e).__module__}.{type(e).__name__}{e.args!r}")


COPY = f"{TMP}/sig.db"
shutil.copy2(SRC, COPY)
c = sqlite3.connect(COPY)
print("journal_mode =", c.execute("PRAGMA journal_mode").fetchone()[0])
c.execute("CREATE TABLE IF NOT EXISTS _probe(x)")
c.commit()
c.close()

HOLDER = f"{TMP}/holder.py"

print("\n--- 场景A: 写者持未提交写事务（BEGIN IMMEDIATE + INSERT） ---")
with open(HOLDER, "w") as f:
    f.write(
        "import sqlite3,sys,time,os\n"
        "c=sqlite3.connect(sys.argv[1])\n"
        "c.execute('BEGIN IMMEDIATE')\n"
        "c.execute(\"INSERT INTO _probe VALUES ('uncommitted')\")\n"
        "open(sys.argv[2],'w').write('ready')\n"
        "time.sleep(25)\n"
    )
for mode, kill_it in (("A1 写事务进行中", False), ("A2 写事务被 SIGKILL 强杀", True)):
    flag = f"{TMP}/ready.flag"
    if os.path.exists(flag):
        os.unlink(flag)
    p = subprocess.Popen([sys.executable, "-B", HOLDER, COPY, flag])
    for _ in range(200):
        if os.path.exists(flag):
            break
        time.sleep(0.05)
    print(f" {mode}:")
    print("    wal size =", os.path.getsize(COPY + "-wal") if os.path.exists(COPY + "-wal") else "no -wal",
          "| shm =", os.path.exists(COPY + "-shm"))
    try_ro(COPY, mode)
    if kill_it:
        p.send_signal(signal.SIGKILL)
        p.wait()
    else:
        p.terminate()
        p.wait()
    time.sleep(0.3)
    print("    收尾后 wal =", os.path.getsize(COPY + "-wal") if os.path.exists(COPY + "-wal") else "no -wal",
          "| shm =", os.path.exists(COPY + "-shm"))

print("\n--- 场景C: 非空 -wal 且删除 -shm（无写者协调） ---")
if os.path.exists(COPY + "-shm"):
    os.unlink(COPY + "-shm")
print("    wal =", os.path.getsize(COPY + "-wal") if os.path.exists(COPY + "-wal") else "no -wal",
      "| shm =", os.path.exists(COPY + "-shm"))
try_ro(COPY, "C")

print("\n--- 场景D: duckdb read_only 报错形态 ---")
try_duck(f"{TMP}/missing.db", "D1 文件不存在(ro)")
DUCK = f"{TMP}/d.duckdb"
dc = duckdb.connect(DUCK)
dc.execute("CREATE TABLE t(a int)")
dc.close()
HH = f"{TMP}/holderd.py"
with open(HH, "w") as f:
    f.write(
        "import duckdb,sys,time\n"
        "c=duckdb.connect(sys.argv[1])\n"
        "c.execute('CREATE TABLE rw(x int)')\n"
        "open(sys.argv[2],'w').write('ready')\n"
        "time.sleep(25)\n"
    )
flag = f"{TMP}/ready2.flag"
p = subprocess.Popen([sys.executable, "-B", HH, DUCK, flag])
for _ in range(200):
    if os.path.exists(flag):
        break
    time.sleep(0.05)
try_duck(DUCK, "D2 另一进程持读写锁时(ro)")
p.terminate()
p.wait()
time.sleep(0.5)
print("\n=== 结论看上面：[A1/A2/C] 里哪一条复现 'unable to open database file' ===")
