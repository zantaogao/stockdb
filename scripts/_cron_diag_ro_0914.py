#!/usr/bin/env python3
"""只读诊断3：executions.db 的 mode=ro 打不开是否可复现（同 patrol 报错形态）。
顺带体检各 sqlite 库的头部/锁文件，并在同一状态下反复 20 次 mode=ro 连接。"""
import os, sqlite3

FILES = [
    "/Users/zantao/.hermes/cron/executions.db",
    "/Users/zantao/.hermes/cron/cron.db",
    "/Users/zantao/.hermes/cron/jobs.db",
    "/Users/zantao/.hermes/cron/notepad.db",
    "/Users/zantao/.hermes/stockdb/signals.db",
    "/Users/zantao/.hermes/stockdb/ledger.db",
]


def head(p, n=16):
    try:
        with open(p, "rb") as f:
            b = f.read(n)
        return b.hex() + " | " + "".join(chr(c) if 32 <= c < 127 else "." for c in b)
    except Exception as e:
        return f"ERR {e!r}"


for p in FILES:
    print(f"\n--- {p} ---")
    if not os.path.exists(p):
        print("  不存在"); continue
    print("  size:", os.path.getsize(p), "| head:", head(p))
    print("  -wal:", os.path.getsize(p + "-wal") if os.path.exists(p + "-wal") else "none",
          "| -shm:", "yes" if os.path.exists(p + "-shm") else "no")
    errs = {}
    ok = 0
    for i in range(20):
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
            c.close()
            ok += 1
        except Exception as e:
            k = f"{type(e).__name__}{e.args!r}"
            errs[k] = errs.get(k, 0) + 1
    print(f"  mode=ro x20: 成功 {ok}, 失败 {sum(errs.values())} {errs if errs else ''}")
    # 对照：默认(读写)连接
    try:
        c = sqlite3.connect(p, timeout=5)
        n = c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        c.close()
        print(f"  默认连接 OK (tables={n})")
    except Exception as e:
        print(f"  默认连接 FAIL -> {type(e).__name__}{e.args!r}")
