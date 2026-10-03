"""Dry-run: replicate backup.sh rotation logic with k=2 over current tushare snapshots."""
import glob, os

TS_DIR = os.path.expanduser("~/.hermes/stockdb/db_backups/tushare")
snaps = sorted(d for d in glob.glob(TS_DIR + "/2*/") if os.path.isdir(d))
print("现有快照:", [os.path.basename(s.rstrip('/')) for s in snaps])
cnt = len(snaps)
k = 2
keep = [s for i, s in enumerate(snaps, 1) if i <= cnt - k]
print("awk 逻辑 (k=2) 将删除:", [os.path.basename(s.rstrip('/')) for s in keep])
print("保留最新", k, "份:", [os.path.basename(s.rstrip('/')) for s in snaps if s not in keep])

# 模拟 tushare 校验: /usr/bin/python3 全表扫描
import duckdb
conn = duckdb.connect(os.path.expanduser("~/.hermes/stockdb/tushare.db"), read_only=True)
for tbl in ["daily", "daily_basic"]:
    print(tbl, "rows:", conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
conn.close()
print("校验口径模拟通过")
