#!/usr/bin/env python3
"""回填历史评分：对 score_history.json 中各日期各股票，用当前模型重新预测"""
import json, sys, os, shutil, time
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.scoring import score_stock, _load_models
import duckdb

SCORE_PATH = BASE / 'score_history.json'
DB_PATH = BASE / 'stock.db'

# 备份
backup = str(SCORE_PATH) + '.bak'
shutil.copy2(str(SCORE_PATH), backup)
print(f"✅ 已备份到 {backup}")

# 加载现有评分历史
with open(SCORE_PATH) as f:
    hist = json.load(f)

_load_models()
print(f"✅ 模型已加载")

updated = 0
skipped = 0
errors = []

for date_key in sorted(hist.keys()):
    if date_key.startswith('_'):  # skip metadata keys
        continue
    
    stocks = hist[date_key]
    print(f"\n📅 {date_key} ({len(stocks)} stocks):")
    
    for code in list(stocks.keys()):
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
                skipped += 1
                print(f"  ⏭ {code}: 数据不足({len(rows)}行)")
                continue
            
            sc = score_stock(code, rows)
            if sc is None:
                skipped += 1
                continue
            
            # Update existing entry with new model predictions
            entry = stocks[code]
            entry['reg10'] = sc.get('reg10_pred', 0)
            entry['reg20'] = sc.get('reg_pred', 0)
            entry['reg40'] = sc.get('reg40_pred', 0)
            entry['v9_fusion'] = sc.get('fusion_v9', 0)
            entry['final_score'] = sc.get('final_score', 0)
            # Keep original fields but update reg with new model
            if sc.get('reg_pred') is not None:
                entry['reg'] = sc['reg_pred']
            entry['fusion'] = sc.get('fusion_v9', entry.get('fusion', 0))
            
            updated += 1
            if updated % 20 == 0:
                print(f"  ... {updated} done", flush=True)
                
        except Exception as e:
            errors.append((date_key, code, str(e)))
            print(f"  ❌ {code} on {date_key}: {e}", flush=True)
    
    # Save progress after each date
    hist['_version'] = 'v9_backfill'
    with open(SCORE_PATH, 'w') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

print(f"\n{'='*50}")
print(f"✅ 完成: {updated} 更新, {skipped} 跳过, {len(errors)} 错误")
if errors:
    print(f"❌ 错误详情:")
    for dt, code, err in errors:
        print(f"  {dt} {code}: {err}")
print(f"备份: {backup}")
