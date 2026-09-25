#!/usr/bin/env python3
"""只读诊断5：钉死判定条件——WAL 库 + 侧车 -wal 缺失时 mode=ro 必失败？"""
import os, shutil, sqlite3

TMP = "/tmp/r3"
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
SRC = os.path.expanduser("~/.hermes/stockdb/signals.db")


def ro(p, extra=""):
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro{extra}", uri=True, timeout=5)
        n = c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        c.close()
        return f"OK(tables={n})"
    except Exception as e:
        return f"FAIL {type(e).__name__}{e.args!r}"


def mk(name):
    p = f"{TMP}/{name}"
    shutil.copy2(SRC, p)
    for s in ("-wal", "-shm"):
        if os.path.exists(p + s):
            os.unlink(p + s)
    return p


def state(p):
    return (f"wal={'%.0fB' % os.path.getsize(p+'-wal') if os.path.exists(p+'-wal') else 'NONE'} "
            f"shm={'yes' if os.path.exists(p+'-shm') else 'NONE'}")


a = mk("a.db")
print("A 仅主文件(无 -wal/-shm)      :", state(a), "->", ro(a))
print("A' +immutable=1              :", ro(a, "&immutable=1"))

b = mk("b.db")
open(b + "-wal", "wb").close()
print("B 空 -wal 存在(0B)           :", state(b), "->", ro(b))

c = mk("c.db")
k = sqlite3.connect(c)
k.execute("CREATE TABLE IF NOT EXISTS _p(x)")
k.execute("INSERT INTO _p VALUES (1)")
k.commit()
k.close()
print("C 我自己的 rw 连接建过侧车   :", state(c), "->", ro(c))
if os.path.exists(c + "-wal"):
    os.unlink(c + "-wal")
print("C' 再删掉 -wal               :", state(c), "->", ro(c))

d = mk("d.db")
k = sqlite3.connect(d)
k.execute("CREATE TABLE IF NOT EXISTS _p(x)")
k.execute("INSERT INTO _p VALUES (1)")
k.commit()
k.execute("PRAGMA wal_checkpoint(TRUNCATE)")
k.close()
print("D checkpoint(TRUNCATE)后     :", state(d), "->", ro(d))

print("\n结论规则: WAL 库 + 无 -wal 侧车 => 只读(mode=ro)连接 ENOENT => 'unable to open database file'")
