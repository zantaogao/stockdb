#!/usr/bin/env python3
"""回填缺失日期评分：05-26到05-29 + 06-01"""
import json, sys, shutil
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.scoring import score_stock, _load_models
import duckdb

SCORE_PATH = BASE / 'score_history.json'
DB_PATH = BASE / 'stock.db'
HOLD_PATH = BASE / 'holdings.json'

# 需要补的日期（交易日）
MISSING_DATES = ['2026-05-26','2026-05-27','2026-05-28','2026-05-29','2026-06-01']

# 读取所有已有股票+当前持仓）
with open(SCORE_PATH) as f:
    hist = json.load(f)

all_codes = set()
for dt, stocks in hist.items():
    if dt.startswith('_'): continue
    for code in stocks:
        all_codes.add(code)

with open(HOLD_PATH) as f:
    h = json.load(f)
for p in h.get('positions', []):
    if p.get('status') in ('hold','watch_active','watch_cold'):
        all_codes.add(p['code'])

codes = sorted(all_codes)
print(f'需覆盖股票: {len(codes)} 只: {codes}')

_load_models()
print('模型已加载')

backup = str(SCORE_PATH) + '.bak2'
shutil.copy2(str(SCORE_PATH), backup)
print(f'备份: {backup}')

total_updated = 0
for date_key in MISSING_DATES:
    entry_count = 0
    for code in codes:
        try:
            conn = duckdb.connect(str(DB_PATH), read_only=True)
            rows = conn.execute(f"""
                SELECT date, close, open, high, low, COALESCE(change_pct, 0), volume, amount
                FROM stock_daily WHERE stock_code = '{code}'
                AND date <= '{date_key}'
                ORDER BY date DESC LIMIT 120
            """).fetchall()
            conn.close()
            
            if len(rows) < 120:
                continue
            
            sc = score_stock(code, rows)
            if sc is None:
                continue
            
            # Save to hist
            if date_key not in hist:
                hist[date_key] = {}
            
            hist[date_key][code] = {
                'reg10': sc.get('reg10_pred', 0),
                'reg20': sc.get('reg_pred', 0),
                'reg40': sc.get('reg40_pred', 0),
                'v9_fusion': sc.get('fusion_v9', 0),
                'fusion': sc.get('fusion_v9', 0),
                'lstm': sc.get('lstm', 50),
                'rule': 50,
            }
            entry_count += 1
            total_updated += 1
            
        except Exception as e:
            print(f'  ❌ {code} on {date_key}: {e}')
    
    print(f'  {date_key}: {entry_count}/{len(codes)} 只')
    
    # Save after each date
    hist['_version'] = 'v9_backfill_v2'
    with open(SCORE_PATH, 'w') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

print(f'\n✅ 完成: 补了 {total_updated} 条, 覆盖 {len(MISSING_DATES)} 个日期')
