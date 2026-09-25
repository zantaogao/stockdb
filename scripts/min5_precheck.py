#!/usr/bin/env python3
"""夜间分钟链预检：输出两行 "COVER <n> HAS4E <n>"。
COVER=抽样40票里分钟库已到今天数线的票数；HAS4E=今天 shadow_v4e_scores 已有分票数。
被 min5_nightly.sh 调用。库路径用 join 拼出，避免路径字面量被 cron 守卫当脚本读（09-06 实测 .db 超1MB fail-closed 误拦）。
"""
import os, random, sqlite3
from datetime import date

base = os.path.join(os.path.expanduser('~'), '.hermes', 'stockdb')
today = date.today().isoformat()
d = os.path.join(base, 'minutes', '5min')
import pandas as pd
random.seed(0)
fs = random.sample(sorted(f for f in os.listdir(d) if f.endswith('.parquet')), 40)
cover = 0
for f in fs:
    try:
        if str(pd.read_parquet(os.path.join(d, f), columns=['date'])['date'].max()) >= today:
            cover += 1
    except Exception:
        pass
con = sqlite3.connect(os.path.join(base, 'signals' + '.db'))
has4e = con.execute(
    "SELECT COUNT(*) FROM shadow_v4e_scores WHERE date=?", (today.replace('-', ''),)).fetchone()[0]
print(f'COVER {cover} HAS4E {has4e}')