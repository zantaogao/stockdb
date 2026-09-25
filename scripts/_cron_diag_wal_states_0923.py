"""对照实验：WAL 库在 -wal/-shm 是否存在时，sqlite3 mode=ro 能否打开。

状态：
  A) 副本保留 -wal/-shm（写者刚写过）
  B) 副本删掉 -wal/-shm（写者干净收尾后的常态）
  C) 只删 -wal 保留 -shm
判据：B 失败 = patrol 在写者干净收尾后必然误报，根因在"ro 打开 WAL 库需 shm"。
"""
import os, shutil, sqlite3, tempfile

BASE = os.path.expanduser("~/.hermes/stockdb")
src = f"{BASE}/signals.db"
tmp = tempfile.mkdtemp(prefix="wal_state_")
print("src journal-ish aux:", [f for f in os.listdir(BASE) if f.startswith("signals.db-")])


def prep(name, keep_wal, keep_shm):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "signals.db")
    shutil.copy2(src, dst)
    # 用 rw 打开一次，让 sqlite 生成 -wal/-shm
    c = sqlite3.connect(dst)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("select count(*) from fusion_3f_signals").fetchone()
    c.close()
    if not keep_wal and os.path.exists(dst + "-wal"):
        os.remove(dst + "-wal")
    if not keep_shm and os.path.exists(dst + "-shm"):
        os.remove(dst + "-shm")
    state = {s: os.path.exists(dst + s) for s in ("-wal", "-shm")}
    try:
        c = sqlite3.connect(f"file:{dst}?mode=ro", uri=True, timeout=5)
        n = c.execute("select count(*) from fusion_3f_signals").fetchone()[0]
        c.close()
        res = f"OK rows={n}"
    except Exception as e:
        res = f"FAIL {repr(e)[:70]}"
    print(f"  {name}: wal={state['-wal']} shm={state['-shm']} -> mode=ro {res}")


prep("A_wal+shm", True, True)
prep("B_no_wal_no_shm", False, False)
prep("C_shm_only", False, True)
shutil.rmtree(tmp, ignore_errors=True)
