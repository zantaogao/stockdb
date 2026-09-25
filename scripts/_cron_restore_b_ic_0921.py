#!/usr/bin/env python3
"""恢复 ic_shadow_b 6 个被重算覆盖成 NULL 的历史值（09-21 B退役副作用）。
B分从归档CSV重取，IC口径与 shadow_ic_check.py.bak.20260921_retireB 逐字一致。"""
import sqlite3, numpy as np, pandas as pd, csv
from scipy import stats
from pathlib import Path
BASE = Path.home()/'.hermes/stockdb'
import sys; sys.path.insert(0, str(BASE))
from core.db import get_tushare_db

tcon = sqlite3.connect(BASE/'signals.db')
# B分 CSV
bmap_by_date = {}
with open(BASE/'retire/shadow_B_scores_20260921.csv') as f:
    for r in csv.DictReader(f):
        bmap_by_date.setdefault(r['date'], {})[r['code']] = float(r['score'])

tconn = get_tushare_db()
all_days = [str(r[0]) for r in tconn.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
day_pos = {d: i for i, d in enumerate(all_days)}
FWD = 10

def px_of(date_, tcodes):
    out = {}
    arr = list(tcodes)
    for k in range(0, len(arr), 900):
        ch = arr[k:k+900]
        ph = ','.join(['?']*len(ch))
        for tc, c in tconn.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [date_]+ch).fetchall():
            out[str(tc)] = float(c)
    return out

# 受影响日 = ic_shadow_b IS NULL 且 CSV 里有该日 B 分
dirty = [r[0] for r in tcon.execute(
    "SELECT signal_date FROM ic_shadow WHERE ic_shadow_b IS NULL").fetchall()
    if r[0].replace('-','') in bmap_by_date or r[0] in bmap_by_date]
print("需恢复日:", dirty)
for sd in dirty:
    key = sd.replace('-','') if sd.replace('-','') in bmap_by_date else sd
    bmap = bmap_by_date[key]
    sig = pd.read_sql_query("SELECT stock_code AS code, reg10 FROM signal_history WHERE date=?", tcon, params=(sd,)).drop_duplicates('code')
    if len(sig) < 100: print(sd, "sig<100 skip"); continue
    codes = sig['code'].astype(str).tolist()
    tcodes = [f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ" for c in codes]
    end = all_days[day_pos[sd]+FWD]
    p0d, p1d = px_of(sd, tcodes), px_of(end, tcodes)
    p0 = np.array([p0d.get(t, np.nan) for t in tcodes], dtype=float)
    p1 = np.array([p1d.get(t, np.nan) for t in tcodes], dtype=float)
    ok = np.isfinite(p0) & np.isfinite(p1) & (p0 > 0) & (p1 > 0)
    ret = p1[ok]/p0[ok]-1
    ret_all = np.full(len(sig), np.nan); ret_all[ok] = ret
    sb = sig['code'].map(bmap).to_numpy(dtype=float)
    okb = ok & np.isfinite(sb)
    ic_b = stats.spearmanr(sb[okb], ret_all[okb])[0] if okb.sum() >= 100 else None
    assert np.isfinite(ic_b), f"{sd} 重算失败"
    tcon.execute("UPDATE ic_shadow SET ic_shadow_b=? WHERE signal_date=?", (round(float(ic_b),6), sd))
    print(sd, "恢复 ic_shadow_b =", round(float(ic_b),6), f"(n={okb.sum()})")
tcon.commit()
n = tcon.execute("SELECT COUNT(*) FROM ic_shadow WHERE ic_shadow_b IS NOT NULL").fetchone()[0]
print("最终 ic_shadow_b 非空行数:", n, "（应=19）")
