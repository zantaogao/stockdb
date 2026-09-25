#!/usr/bin/env python3
"""为新加入观察的9只股票补历史评分（05-26 ~ 06-05）"""
import json, sys
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.scoring import score_stock, _load_models
import duckdb

SCORE_PATH = BASE / 'score_history.json'
DB_PATH = BASE / 'stock.db'

new_codes = ['301486','603929','301123','300751','002149','300503','300604','600118','300782']
dates = ['2026-05-26','2026-05-27','2026-05-28','2026-05-29','2026-05-30',
         '2026-06-01','2026-06-02','2026-06-03','2026-06-04','2026-06-05']

_load_models()
print('模型已加载')

with open(SCORE_PATH) as f:
    sh = json.load(f)

total = 0
for code in new_codes:
    count = 0
    for dt in dates:
        try:
            conn = duckdb.connect(str(DB_PATH), read_only=True)
            rows = conn.execute(f"""
                SELECT date, close, open, high, low, COALESCE(change_pct, 0), volume, amount
                FROM stock_daily WHERE stock_code='{code}'
                AND date <= '{dt}'
                ORDER BY date DESC LIMIT 120
            """).fetchall()
            conn.close()
            
            if len(rows) < 120:
                continue
            
            sc = score_stock(code, rows)
            if sc is None:
                continue
            
            if dt not in sh:
                sh[dt] = {}
            
            sh[dt][code] = {
                'reg10': sc.get('reg10_pred', 0),
                'reg20': sc.get('reg_pred', 0),
                'reg40': sc.get('reg40_pred', 0),
                'fusion': sc.get('fusion_v9', 0),
                'lstm': sc.get('lstm', 50),
                'rule': 50,
            }
            count += 1
            total += 1
        except Exception as e:
            print(f'  {code} {dt}: {e}')
    
    print(f'  {code}: 补了 {count}/{len(dates)} 天')

sh['_version'] = 'v6+_backfill_new'
with open(SCORE_PATH, 'w') as f:
    json.dump(sh, f, ensure_ascii=False, indent=2)

print(f'\n✅ 完成: 共补 {total} 条')
