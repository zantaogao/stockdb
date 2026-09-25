#!/bin/bash
# update_data.sh — 每日数据更新标准入口（只更新，不 dump）
# 流程: 增量更新(含全表强读校验+失败回滚) → 活库健康复验 → 输出摘要
# 用法: bash update_data.sh
set -uo pipefail
cd "$(dirname "$0")"

echo "=============================================="
echo " tushare.db 每日数据更新"
date '+ 开始: %Y-%m-%d %H:%M:%S'
echo "=============================================="

# ── 1. 增量更新（脚本内部: 克隆→写临时库→全表强读→原子交换→复验回滚）──
echo "── [1/2] 执行增量更新 ──"
python3 -B scripts/update_tushare_api.py
RC=$?
if [ $RC -ne 0 ]; then
  echo "  ❌ 增量更新失败（exit=$RC）"
  echo "  ⚠️ 若已自动回滚，活库仍是更新前状态，可安全重试"
  exit $RC
fi

# ── 2. 活库健康复验 + 数据摘要 ──
echo "── [2/2] 活库复验 ──"
python3 << 'EOF'
import duckdb
DB = 'tushare.db'
try:
    conn = duckdb.connect(DB, read_only=True)
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name"
    ).fetchall()
    # 关键表全表强读（触发所有 block checksum 校验）
    total = 0
    for (t,) in tables:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM "{t}"')
        cnt = 0
        while True:
            batch = cur.fetchmany(50000)
            if not batch:
                break
            cnt += len(batch)
        cur.close()
        total += cnt
    # 摘要
    daily = conn.execute("SELECT max(trade_date), count(*) FROM daily").fetchone()
    dbasic = conn.execute("SELECT max(trade_date) FROM daily_basic").fetchone()[0]
    conn.close()
    print(f"  ✅ 活库健康: {len(tables)} 表, {total:,} 行, 全表强读通过")
    print(f"  📊 daily 最新: {daily[0]} ({daily[1]:,} 行/日) | daily_basic 最新: {dbasic}")
except Exception as e:
    print(f"  ❌ 活库复验失败: {str(e)[:120]}")
    exit(1)
EOF
RC=$?
if [ $RC -ne 0 ]; then
  exit $RC
fi

date '+ 完成: %Y-%m-%d %H:%M:%S'
echo "=============================================="
echo "✅ 数据更新完成"
