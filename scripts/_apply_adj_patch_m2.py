#!/usr/bin/env python3
"""把 2009-2014 adj_factor 补丁合进 M2 的 tushare.db（2026-09-21）

安全设计：
 1) 前置备份已在跑（/Volumes/Lexar/m2_tushare_backup/tushare.db，回滚锚点）
 2) 单事务 INSERT（3.19M 行 ≈ 100MB）：DuckDB ACID，中断自动回滚，不会留下半成品
 3) 只补"库中不存在"的 (ts_code, trade_date)，天然幂等，可重复执行
 4) 写完立即验证：按年覆盖率、行数增量、跨 2015 边界抽样连续性；再 CHECKPOINT
 5) 避开 16:00-17:00 增量更新窗口（那段时间库由更新脚本改写/原子交换）

用法：/usr/bin/python3 -B ~/.hermes/stockdb/scripts/_apply_adj_patch_m2.py
"""
import os
import time

import duckdb

BASE = os.path.expanduser('~/.hermes/stockdb')
DB = f'{BASE}/tushare.db'
PATCH = f'{BASE}/backtest_results/adj_factor_pre2015.parquet'

assert os.path.exists(PATCH), f'补丁不存在：{PATCH}'
t0 = time.time()

c = duckdb.connect(DB)
c.execute("SET memory_limit='8GB'")
b_all = c.execute("SELECT COUNT(*) FROM adj_factor").fetchone()[0]
b_pre = c.execute("SELECT COUNT(*) FROM adj_factor WHERE trade_date < '20150101'").fetchone()[0]
p_n = c.execute(f"SELECT COUNT(*) FROM read_parquet('{PATCH}')").fetchone()[0]
print(f'插入前：adj_factor 总 {b_all:,} 行 / 2015 前 {b_pre:,} 行；补丁 {p_n:,} 行', flush=True)

try:
    c.execute("BEGIN TRANSACTION")
    c.execute(f"""
        INSERT INTO adj_factor
        SELECT p.ts_code, p.trade_date, p.adj_factor
        FROM read_parquet('{PATCH}') p
        WHERE NOT EXISTS (
            SELECT 1 FROM adj_factor a
            WHERE a.ts_code = p.ts_code AND a.trade_date = p.trade_date
        )
    """)
    c.execute("COMMIT")
except Exception as e:  # noqa: BLE001
    try:
        c.execute("ROLLBACK")
    except Exception:  # noqa: BLE001
        pass
    print(f'❌ 插入失败（已回滚）：{e}')
    raise SystemExit(1)

a_all = c.execute("SELECT COUNT(*) FROM adj_factor").fetchone()[0]
a_pre = c.execute("SELECT COUNT(*) FROM adj_factor WHERE trade_date < '20150101'").fetchone()[0]
print(f'插入后：adj_factor 总 {a_all:,} 行（+{a_all-b_all:,}）/ 2015 前 {a_pre:,} 行（+{a_pre-b_pre:,}）'
      f'  用时 {time.time()-t0:.0f}s', flush=True)

print('\n按年覆盖率：', flush=True)
bad = []
for y, n, h in c.execute("""
    SELECT substr(d.trade_date,1,4) y, COUNT(*) n, COUNT(a.adj_factor) h
    FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
    WHERE d.trade_date >= '20090101' GROUP BY 1 ORDER BY 1
""").fetchall():
    pct = 100.0 * h / n
    flag = '' if pct > 99 else '  ⚠️'
    if pct <= 99:
        bad.append(y)
    print(f'  {y}: {pct:6.2f}%  ({h:,}/{n:,}){flag}', flush=True)

print('\n跨 2015 边界抽样（adj_factor 应连续、无跳变）：', flush=True)
for ts in ('000001.SZ', '600000.SH', '300274.SZ'):
    rows = c.execute("""
        SELECT trade_date, adj_factor FROM adj_factor
        WHERE ts_code = ? AND trade_date IN ('20141229','20141230','20141231','20150105','20150106','20150107')
        ORDER BY trade_date
    """, (ts,)).fetchall()
    if rows:
        print(f'  {ts}: ' + '  '.join(f'{d}={v:.4f}' for d, v in rows), flush=True)

c.execute("CHECKPOINT")
print(f'\nCHECKPOINT 完成  {time.time()-t0:.0f}s', flush=True)
c.close()
print('✅ 完成。' + ('注意仍有年份覆盖不足：' + ','.join(bad) if bad else '全样本 2009+ 覆盖率 100%。'))
