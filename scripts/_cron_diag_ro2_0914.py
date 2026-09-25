#!/usr/bin/env python3
"""只读诊断4：定位 mode=ro 报 'unable to open database file' 的判定条件。
已知: ~/.hermes/cron/{executions,notepad}.db 稳定失败(20/20)，stockdb/{signals,ledger}.db 成功。
变量候选: 目录权限 / 是否 WAL / 有无 -shm / uid。
"""
import os, shutil, sqlite3, stat

TMP = "/tmp/rodiag"
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)


def ro(p, extra=""):
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro{extra}", uri=True, timeout=5)
        n = c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        c.close()
        return f"OK(tables={n})"
    except Exception as e:
        return f"FAIL {type(e).__name__}{e.args!r}"


def meta(p):
    if not os.path.exists(p):
        return "不存在"
    st = os.stat(p)
    return (f"size={st.st_size} mode={oct(st.st_mode & 0o777)} uid={st.st_uid} "
            f"wal={'yes' if os.path.exists(p+'-wal') else 'no'} "
            f"shm={'yes' if os.path.exists(p+'-shm') else 'no'}")


def jmode(p):
    try:
        c = sqlite3.connect(p, timeout=5)
        v = c.execute("PRAGMA journal_mode").fetchone()[0]
        c.close()
        return v
    except Exception as e:
        return repr(e)


CASES = [
    "/Users/zantao/.hermes/cron/executions.db",
    "/Users/zantao/.hermes/cron/notepad.db",
    "/Users/zantao/.hermes/stockdb/signals.db",
    "/Users/zantao/.hermes/stockdb/ledger.db",
]
for p in CASES:
    print(f"\n=== {p} ===")
    print("  ", meta(p), "| journal_mode =", jmode(p))
    print("   就地 mode=ro      :", ro(p))
    print("   就地 mode=ro&immut :", ro(p, "&immutable=1"))
    cp = f"{TMP}/{os.path.basename(p)}"
    shutil.copy2(p, cp)
    print("   副本(/tmp)        :", meta(cp))
    print("   副本 mode=ro      :", ro(cp))
    # 拿一个读写连接压着，再试 ro（shm 必然存在）
    c = sqlite3.connect(cp, timeout=5)
    c.execute("SELECT count(*) FROM sqlite_master").fetchone()
    print("   持有rw连接时 ro   :", ro(cp))
    c.close()
    print("   关闭rw连接后 ro   :", ro(cp))

print("\n=== 目录属性 ===")
for d in ("/Users/zantao/.hermes/cron", "/Users/zantao/.hermes/stockdb", TMP):
    st = os.stat(d)
    print(f"  {d}: mode={oct(st.st_mode & 0o777)} uid={st.st_uid} gid={st.st_gid}")

print("\n=== 新建 WAL 库（无 -shm）→ mode=ro ===")
p = f"{TMP}/newwal.db"
c = sqlite3.connect(p)
c.execute("PRAGMA journal_mode=WAL")
c.execute("CREATE TABLE t(a)")
c.execute("INSERT INTO t VALUES (1)")
c.commit()
c.close()
print("  ", meta(p), "| mode=ro:", ro(p))
p2 = f"{TMP}/newdel.db"
c = sqlite3.connect(p2)
c.execute("CREATE TABLE t(a)")
c.execute("INSERT INTO t VALUES (1)")
c.commit()
c.close()
print("  ", meta(p2), "| mode=ro:", ro(p2))
