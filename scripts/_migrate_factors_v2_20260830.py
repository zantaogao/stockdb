#!/usr/bin/env python3
"""一次性迁移: signals.db 因子表历史(>30天) -> factors.db (DuckDB)
方案 v2.1 §2/§3: 因子表冷层 factors.db, signals.db 保留 30 天热窗(fusion 引擎 ROLLING_WINDOW=20 安全)
边界: new_factors/flow_alpha/vol_adj 保留 date>=2026-07-30 (YYYY-MM-DD, 归一化比较)
      tdx_intraday_feat 保留 date>=20260730 (INTEGER YYYYMMDD)
2026-08-30 手动执行, 前置: signals.db 已 VACUUM INTO 备份
"""
import sqlite3
import duckdb
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
SIG = BASE / 'signals.db'
FAC = BASE / 'factors.db'

CUTOFF_VCHAR = '20260730'   # new_factors/flow_alpha/vol_adj (date VARCHAR YYYY-MM-DD)
CUTOFF_INT = 20260730       # tdx_intraday_feat (date INTEGER YYYYMMDD)

TABLES = [
    ('new_factors',      "REPLACE(date, '-', '') < ?"),
    ('flow_alpha',       "REPLACE(date, '-', '') < ?"),
    ('vol_adj',          "REPLACE(date, '-', '') < ?"),
    ('tdx_intraday_feat', "date < ?"),
]

# 1. 搬迁前 signals.db 各表行数
sconn = sqlite3.connect(str(SIG), timeout=30)
before = {}
for t, _ in TABLES:
    before[t] = sconn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]

# 2. duckdb 跨库搬 (ATTACH SQLite)
dconn = duckdb.connect(str(FAC))
dconn.execute(f"ATTACH '{SIG}' AS sig (TYPE sqlite)")
moved = {}
for t, cond in TABLES:
    cutoff = CUTOFF_INT if t == 'tdx_intraday_feat' else CUTOFF_VCHAR
    # 目标表已存在(空壳), 用 INSERT INTO ... SELECT 追加
    n = dconn.execute(f"INSERT INTO {t} SELECT * FROM sig.{t} WHERE {cond}", [cutoff]).fetchone()
    moved[t] = n[0] if n else 0
    print(f"搬入 factors.{t}: {moved[t]} 行")
dconn.execute("CHECKPOINT")
dconn.close()

# 3. 校验: factors 库搬入后行数 = 原 signals 历史行数
dconn = duckdb.connect(str(FAC), read_only=True)
for t, _ in TABLES:
    total = dconn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    print(f"校验 factors.{t} 总行数={total} (搬入={moved[t]})")
    assert total == moved[t], f"factors.{t} 行数不符: {total} != {moved[t]}"
dconn.close()

# 4. 删除 signals.db 历史 + VACUUM
for t, cond in TABLES:
    cutoff = CUTOFF_INT if t == 'tdx_intraday_feat' else CUTOFF_VCHAR
    cur = sconn.execute(f"DELETE FROM {t} WHERE {cond}", [cutoff])
    print(f"signals.{t} 删除 {cur.rowcount} 行")
sconn.commit()
sconn.execute("VACUUM")
sconn.close()

# 5. 终验: signals.db 剩余行数 + 剩余日期窗口
sconn = sqlite3.connect(str(SIG), timeout=30)
print("\n=== 终验 ===")
for t, _ in TABLES:
    remain = sconn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    mn = sconn.execute(f"SELECT MIN(date) FROM {t}").fetchone()[0]
    mx = sconn.execute(f"SELECT MAX(date) FROM {t}").fetchone()[0]
    print(f"signals.{t}: 剩余 {remain} 行, {mn} ~ {mx} (迁移前 {before[t]})")
    assert remain == before[t] - moved[t], f"signals.{t} 对账失败"
sconn.close()

# 6. fusion 引擎窗口安全检查 (ROLLING_WINDOW=20)
sconn = sqlite3.connect(str(SIG), timeout=30)
n_dates = sconn.execute("SELECT count(DISTINCT REPLACE(date,'-','')) FROM new_factors").fetchone()[0]
print(f"\nfusion 窗口安全: new_factors 剩余 {n_dates} 个交易日 (需要 >= 20) -> {'OK' if n_dates >= 20 else '危险!'}")
sconn.close()
print("\n✅ 迁移完成, 全部校验通过")
