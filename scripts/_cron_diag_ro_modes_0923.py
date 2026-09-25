"""直查真库 signals.db：ro 失败 vs rw 成功，逐 URI 模式定位。"""
import os, sqlite3, subprocess, glob

BASE = os.path.expanduser("~/.hermes/stockdb")
p = f"{BASE}/signals.db"

print("dir stat:", oct(os.stat(BASE).st_mode), "uid=", os.getuid())
print("aux files:", glob.glob(p + "-*"))

for uri, label in [
    (f"file:{p}?mode=ro", "mode=ro"),
    (f"file:{p}?mode=ro&immutable=1", "ro&immutable=1"),
    (f"file:{p}?mode=ro&nolock=1", "ro&nolock=1"),
    (f"file:{p}?mode=rw", "mode=rw"),
    (p, "plain (default)"),
]:
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
        n = con.execute("select count(*) from fusion_3f_signals where replace(date,'-','')='20260923'").fetchone()[0]
        print(f"{label}: OK rows={n}")
        con.close()
    except Exception as e:
        print(f"{label}: FAIL {repr(e)[:80]}")

# 谁占着这个库
r = subprocess.run(["/usr/sbin/lsof", p], capture_output=True, text=True)
print("lsof:", r.stdout[:600] if r.stdout.strip() else "(no holder)")
