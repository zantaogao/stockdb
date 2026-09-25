"""复现 patrol 的 'unable to open database file' 根因：WAL 库 + 目录无写权限。

假设链：
  signals.db 是 journal_mode=wal；只读连接若拿不到目录写权限（无法建 -wal/-shm）
  就报 unable to open database file。本脚本造一个 WAL 库副本，
  把所在目录 chmod 555 后试只读打开，验证该假设。
"""
import os
import shutil
import sqlite3
import stat
import tempfile

BASE = os.path.expanduser("~/.hermes/stockdb")
tmp = tempfile.mkdtemp(prefix="wal_probe_")
db = os.path.join(tmp, "copy.db")
shutil.copy2(f"{BASE}/signals.db", db)

con = sqlite3.connect(db)
con.execute("PRAGMA journal_mode=WAL")
con.execute("select count(*) from fusion_3f_signals").fetchone()
con.close()
for suf in ("-wal", "-shm"):
    print("after writer:", suf, "exists" if os.path.exists(db + suf) else "gone",
          os.path.getsize(db + suf) if os.path.exists(db + suf) else "")

os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)  # 555
print("dir mode:", oct(stat.S_IMODE(os.stat(tmp).st_mode)))
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    print("readonly open on read-only dir: OK, rows =",
          con.execute("select count(*) from fusion_3f_signals").fetchone()[0])
    con.close()
except Exception as e:
    print("readonly open on read-only dir FAIL:", repr(e)[:90])

# 对照：同样只读权限的目录 + delete 模式库
db2 = os.path.join(tmp, "del.db")
os.chmod(tmp, 0o755)
con = sqlite3.connect(db2)
con.execute("PRAGMA journal_mode=DELETE")
con.execute("create table t(x)")
con.execute("insert into t values (1)")
con.close()
os.chmod(tmp, 0o555)
try:
    con = sqlite3.connect(f"file:{db2}?mode=ro", uri=True, timeout=10)
    print("delete-mode db on read-only dir: OK, rows =",
          con.execute("select count(*) from t").fetchone()[0])
    con.close()
except Exception as e:
    print("delete-mode db FAIL:", repr(e)[:90])

os.chmod(tmp, 0o755)
shutil.rmtree(tmp, ignore_errors=True)
