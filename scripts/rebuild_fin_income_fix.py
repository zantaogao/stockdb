#!/usr/bin/env python3
"""补充重建 fin_income：重拉失败/缺失的股票（断点续跑）"""
import os, sys, time, json, warnings
import duckdb
import tushare as ts
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')
BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'tushare.db'
STATE_FILE = BASE / 'tmp_rebuild_fin_income_fix.json'
SLEEP = 0.12
MAX_CONSEC_ERR = 15

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_db():
    tmp = BASE / 'tushare.db.rebuild_tmp'
    return duckdb.connect(str(tmp))

def load_state():
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return {}

def save_state(st):
    tmp = STATE_FILE.with_suffix('.tmp')
    json.dump(st, open(tmp, 'w'), ensure_ascii=False)
    tmp.replace(STATE_FILE)

def pull_one(pro, api_name, ts_code):
    fn = getattr(pro, api_name)
    for attempt in range(3):
        try:
            df = fn(ts_code=ts_code)
            if df is None or len(df) == 0:
                return None
            for c in ['end_date', 'ann_date', 'f_ann_date']:
                if c in df.columns:
                    df[c] = df[c].astype(str).str.replace('-', '').str.replace('.0', '', regex=False)
            return df
        except Exception as e:
            err = str(e)
            if 'limit' in err.lower() or '每分钟' in err or '频率' in err:
                time.sleep(30)
            else:
                time.sleep(2)
    return None

def main():
    pro = ts.pro_api()
    db = get_db()
    state = load_state()

    # 新表列
    new_cols = [r[0] for r in db.execute("DESCRIBE fin_income").fetchall()]
    # 已成功的股票
    done = set(r[0] for r in db.execute("SELECT DISTINCT ts_code FROM fin_income").fetchall())
    # 待拉股票
    stocks = [r[0] for r in db.execute("SELECT ts_code FROM stock_basic ORDER BY ts_code").fetchall()]
    todo = [s for s in stocks if s not in done]
    done_fix = set(state.get('done', []))
    todo = [s for s in todo if s not in done_fix]
    log(f"已完成 {len(done)} 只, 待补 {len(todo)} 只")

    total = 0
    consec_err = 0
    for i, ts_code in enumerate(todo):
        try:
            df = pull_one(pro, 'income', ts_code)
            if df is not None and len(df) > 0:
                df = df[[c for c in new_cols if c in df.columns]]
                if len(df) > 0:
                    db.register('_tmp_df', df)
                    col_list = ', '.join(f'"{c}"' for c in df.columns)
                    db.execute(f"INSERT INTO fin_income ({col_list}) SELECT {col_list} FROM _tmp_df")
                    db.unregister('_tmp_df')
                    total += len(df)
            consec_err = 0
            if (i+1) % 200 == 0:
                db.execute("CHECKPOINT")
                save_state({'done': list(done_fix) + todo[:i+1]})
                log(f"  [{i+1}/{len(todo)}] 累计 +{total:,} 行")
        except Exception as e:
            consec_err += 1
            log(f"  ⚠️ {ts_code}: {str(e)[:70]}")
            if consec_err >= MAX_CONSEC_ERR:
                log(f"  ❌ 连续错误 {consec_err}, 中止")
                db.execute("CHECKPOINT")
                db.close()
                sys.exit(1)
        time.sleep(SLEEP)

    db.execute("CHECKPOINT")
    save_state({'done': list(done_fix) + todo})
    cnt = db.execute("SELECT count(*), count(DISTINCT ts_code) FROM fin_income").fetchone()
    log(f"✅ 补充完成: fin_income = {cnt[0]:,} 行, {cnt[1]} 只")
    db.close()

if __name__ == '__main__':
    main()
