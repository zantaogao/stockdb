#!/usr/bin/env python3
"""验证 40d 训练脚本修复：因子读取口径 + 语法"""
import ast, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))

# 1. 语法检查
for f in ['scripts/train_40d_mac_v1.py']:
    ast.parse(open(f, encoding='utf-8').read())
    print(f'{f}: 语法OK')

# 2. 因子数据抽查：推理侧 get_factor_from_db vs 训练侧 SQL 同源
import duckdb
from core.db import TUSHARE_DB_PATH
from scripts.feat_tushare import get_factor_from_db

conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)

# 抽查 3 只股票最近 3 个交易日的因子（应有真实值，非全 0）
for code in ['600508', '301042', '688720']:
    full = f'{code}.SH' if code.startswith(('6','9')) else f'{code}.SZ'
    days = [r[0] for r in conn.execute(
        "SELECT trade_date FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 3",
        [full]).fetchall()]
    for d in days:
        fv = get_factor_from_db(code, str(d), ['kdj_k', 'cci', 'rsi_12'], conn)
        vals = [fv.get(k, 0) for k in ['kdj_k', 'cci', 'rsi_12']]
        nonzero = sum(1 for v in vals if abs(v) > 1e-9)
        mark = '✅' if nonzero >= 2 else '❌全0?'
        print(f'  {code} {d}: kdj_k={vals[0]:.2f} cci={vals[1]:.2f} rsi_12={vals[2]:.2f} {mark}')

# 3. 训练侧 SQL（extra 列）数据量确认
cnt = conn.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date >= '2022-01-01'").fetchone()[0]
print(f'\n  stk_factor 2022起行数: {cnt:,}')
conn.close()
print('\n验证完成')
