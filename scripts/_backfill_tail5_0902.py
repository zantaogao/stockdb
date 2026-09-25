"""2026-09-02 一次性回填: tdx_intraday_feat 补 tail5_ret / last_vol_share
口径与 tdx_intraday_agg.compute_features 完全一致:
  tail5_ret = 收盘 / 14:55首根 - 1
  last_vol_share = 最后一根量 / 全日量
数据源: tdx_archive.db min1_archive (20260212-20260902, 134交易日)
"""
import sqlite3, duckdb
import numpy as np

BASE = '/Users/zantao/.hermes/stockdb'
arch = duckdb.connect(f'{BASE}/tdx_archive.db', read_only=True)
sig = sqlite3.connect(f'{BASE}/signals.db')

cols = {r[1] for r in sig.execute("PRAGMA table_info(tdx_intraday_feat)").fetchall()}
for _col in ('tail5_ret', 'last_vol_share'):
    if _col not in cols:
        sig.execute(f"ALTER TABLE tdx_intraday_feat ADD COLUMN {_col} REAL")
sig.commit()

have = {r[0] for r in sig.execute(
    "SELECT DISTINCT date FROM tdx_intraday_feat WHERE tail5_ret IS NOT NULL").fetchall()}
dates = [r[0] for r in arch.execute(
    "SELECT DISTINCT date FROM min1_archive ORDER BY date").fetchall()]
todo = [d for d in dates if d not in have]
print(f"生产表已有tail5的日期: {len(have)}, 档案日期: {len(dates)}, 待回填: {len(todo)}")

n_up = 0
for d in todo:
    # 只回填生产表当天有行的票, 与生产口径对齐
    df = arch.execute(f"""
        SELECT m.code, m.tm, m.close, m.volume
        FROM min1_archive m
        WHERE m.date = {d} AND m.close > 0
        ORDER BY m.code, m.tm""").df()
    rows = []
    for code, g in df.groupby('code', sort=False):
        tm = g['tm'].values
        clo = g['close'].values
        vol = g['volume'].values
        if len(clo) < 30:
            continue
        m1455 = np.searchsorted(tm, 14 * 60 + 55)
        if m1455 >= len(clo):
            m1455 = len(clo) - 1
        tail5 = float(clo[-1] / clo[m1455] - 1)
        lvs = float(vol[-1]) / max(float(vol.sum()), 1e-9)
        rows.append((round(tail5, 6), round(lvs, 6), d, code))
    sig.executemany("UPDATE tdx_intraday_feat SET tail5_ret=?, last_vol_share=? WHERE date=? AND code=?", rows)
    n_up += len(rows)
    if d % 20 == 0 or d == todo[-1]:
        print(f"  {d}: {len(rows)} 行")
sig.commit()

print(f"回填完成: {n_up} 行")
chk = sig.execute("SELECT MIN(date),MAX(date),COUNT(*) FROM tdx_intraday_feat WHERE tail5_ret IS NOT NULL").fetchone()
print("覆盖检查:", chk)
hit = sig.execute("""SELECT COUNT(*) FROM tdx_intraday_feat WHERE tail5_ret>0.015""").fetchone()[0]
tot = sig.execute("SELECT COUNT(*) FROM tdx_intraday_feat WHERE tail5_ret IS NOT NULL").fetchone()[0]
print(f"tail5>1.5% 命中率: {hit}/{tot} = {hit/max(tot,1)*100:.2f}%")
sig.close(); arch.close()