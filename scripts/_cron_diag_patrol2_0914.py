#!/usr/bin/env python3
"""只读诊断2：patrol 的 mode=ro 连接在"WAL 有未检查点帧 / 写者高频提交"下是否报
'unable to open database file'（复现 22:00 链尾部 ❌）。对象仍是 /tmp 副本。"""
import os, shutil, sqlite3, subprocess, sys, time

TMP = "/tmp/patrolprobe2"
SRC = os.path.expanduser("~/.hermes/stockdb/signals.db")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
COPY = f"{TMP}/sig.db"
shutil.copy2(SRC, COPY)
c = sqlite3.connect(COPY)
c.execute("CREATE TABLE IF NOT EXISTS _probe(x)")
c.commit()
c.close()


def ro():
    return sqlite3.connect(f"file:{COPY}?mode=ro", uri=True, timeout=10)


def wal():
    p = COPY + "-wal"
    return os.path.getsize(p) if os.path.exists(p) else "none"


print("=== E1: 已提交写入(留下 WAL 帧) + 删除 -shm → mode=ro ===")
c = sqlite3.connect(COPY)
c.execute("INSERT INTO _probe VALUES ('committed')")
c.commit()
c.close()
print("  commit 后 wal =", wal(), "| shm =", os.path.exists(COPY + "-shm"))
if os.path.exists(COPY + "-shm"):
    os.unlink(COPY + "-shm")
print("  删 shm 后 wal =", wal(), "| shm =", os.path.exists(COPY + "-shm"))
try:
    k = ro()
    print("  mode=ro OK, count =", k.execute("SELECT count(*) FROM _probe").fetchone()[0])
    k.close()
except Exception as e:
    print(f"  mode=ro FAIL -> {type(e).__name__}{e.args!r}")

print("\n=== E2: 只剩非空 -wal（shm 与写者都没有）→ mode=ro ===")
if os.path.exists(COPY + "-shm"):
    os.unlink(COPY + "-shm")
print("  wal =", wal(), "| shm =", os.path.exists(COPY + "-shm"))
try:
    k = ro()
    print("  mode=ro OK, count =", k.execute("SELECT count(*) FROM _probe").fetchone()[0])
    k.close()
except Exception as e:
    print(f"  mode=ro FAIL -> {type(e).__name__}{e.args!r}")

print("\n=== G: 写者高频提交(20s) 期间反复 mode=ro 连接 ===")
H = f"{TMP}/hot.py"
with open(H, "w") as f:
    f.write(
        "import sqlite3,sys,time\n"
        "c=sqlite3.connect(sys.argv[1],timeout=30)\n"
        "open(sys.argv[2],'w').write('ready')\n"
        "t=time.time()\n"
        "i=0\n"
        "while time.time()-t < 20:\n"
        "    i+=1\n"
        "    c.execute('INSERT INTO _probe VALUES (?)',('hot%d'%i,))\n"
        "    c.commit()\n"
        "    time.sleep(0.002)\n"
        "open(sys.argv[3],'w').write(str(i))\n"
    )
flag, out = f"{TMP}/r.flag", f"{TMP}/n.txt"
p = subprocess.Popen([sys.executable, "-B", H, COPY, flag, out])
for _ in range(200):
    if os.path.exists(flag):
        break
    time.sleep(0.05)
msgs, ok, tot, t0 = {}, 0, 0, time.time()
while time.time() - t0 < 20:
    tot += 1
    try:
        k = ro()
        k.execute("SELECT count(*) FROM new_factors").fetchone()
        k.close()
        ok += 1
    except Exception as e:
        msgs[f"{type(e).__name__}{e.args!r}"] = msgs.get(f"{type(e).__name__}{e.args!r}", 0) + 1
    time.sleep(0.01)
p.wait()
print(f"  尝试 {tot} 次: 成功 {ok}, 失败 {tot-ok}")
for m, n in msgs.items():
    print(f"    失败{n}次: {m}")
print("  写者写入条数:", open(out).read() if os.path.exists(out) else "?")
print("\n（若 G 组有 'unable to open database file' 即证明：写者活跃期 mode=ro 连接偶发打不开）")
