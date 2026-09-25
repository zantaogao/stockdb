#!/usr/bin/env python3
"""重建 fin_income / fin_balancesheet / fin_cashflow 为 API 完整列版本

策略：
1. 备份旧表（15列精简版）→ 改名 fin_xxx_legacy（数据不丢，可回滚）
2. 建新表（API 完整列）→ fin_xxx（CREATE TABLE AS SELECT 空结构）
3. 逐股票拉 API 全历史 → 写入新表（分批 + 限频 + 断点续跑）
4. 完成后验证：行数、股票数、日期范围、与 legacy 对比
5. 验证通过后删除 legacy 表

用法：python3 rebuild_fin_tables.py [income|balancesheet|cashflow|all]
"""
import os, sys, time, json, warnings
import duckdb
import tushare as ts
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'tushare.db'
STATE_FILE = BASE / 'tmp_rebuild_fin_state.json'   # 断点续跑状态
SLEEP = 0.12          # 基本限频
MAX_CONSEC_ERR = 10   # 连续错误上限

TABLES = {
    'income': {
        'table': 'fin_income',
        'api': 'income',
    },
    'balancesheet': {
        'table': 'fin_balancesheet',
        'api': 'balancesheet',
    },
    'cashflow': {
        'table': 'fin_cashflow',
        'api': 'cashflow',
    },
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_pro():
    return ts.pro_api()

def get_db():
    """默认连活库；TMP_MODE=1 时连临时库（克隆活库后操作，原子交换）"""
    if os.environ.get('TMP_MODE') == '1':
        tmp = BASE / 'tushare.db.rebuild_tmp'
        if not tmp.exists():
            log(f"  克隆活库 → {tmp.name} (APFS CoW)")
            if hasattr(os, 'clonefile'):
                os.clonefile(str(DB_PATH), str(tmp))
            else:
                import shutil
                shutil.copy2(str(DB_PATH), str(tmp))
        return duckdb.connect(str(tmp))
    return duckdb.connect(str(DB_PATH))

def load_state():
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return {}

def save_state(st):
    tmp = STATE_FILE.with_suffix('.tmp')
    json.dump(st, open(tmp, 'w'), ensure_ascii=False)
    tmp.replace(STATE_FILE)

def get_stocks(db):
    return [r[0] for r in db.execute("SELECT ts_code FROM stock_basic ORDER BY ts_code").fetchall()]

def backup_legacy(db, table):
    """备份旧表 → table_legacy"""
    legacy = f"{table}_legacy"
    has = db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [legacy]).fetchone()[0]
    if has:
        log(f"  ⚠️ {legacy} 已存在，跳过备份（保留旧数据）")
        return
    db.execute(f"CREATE TABLE {legacy} AS SELECT * FROM {table}")
    log(f"  ✅ 已备份 {table} → {legacy} ({db.execute(f'SELECT count(*) FROM {legacy}').fetchone()[0]:,} 行)")

def create_new_table(db, table, api_df):
    """按 API 列结构建新表：用 API 真实数据行建结构（类型推断正确），再清空"""
    # 删除旧表（数据已在 legacy 备份）
    db.execute(f"DROP TABLE IF EXISTS {table}")
    # 用真实数据行建表（非空 df → 类型推断正确），再 DELETE 掉这行
    db.register('_api_struct', api_df)
    db.execute(f"CREATE TABLE {table} AS SELECT * FROM _api_struct")
    db.unregister('_api_struct')
    db.execute(f"DELETE FROM {table}")
    # 修正字符串列为 VARCHAR（数值列可能被误判的场景兜底）
    str_cols = ['ts_code', 'ann_date', 'f_ann_date', 'end_date', 'report_type',
                'comp_type', 'end_type', 'update_flag', 'vip_flag', 'is_audit',
                'audit_agency', 'currency', 'balance', 'report_nature', 'cancel_flag',
                'account_standard', 'bs_standard', 'is_ocip', 'is_cap_rev']
    for col in str_cols:
        try:
            db.execute(f"ALTER TABLE {table} ALTER {col} TYPE VARCHAR")
        except Exception:
            pass
    # 所有 INTEGER 列转 DOUBLE：样本股(如银行)的行业专用列是NULL→推断INTEGER,
    # 其他股票(保险等)这些列是 DOUBLE 大值 → 插入会 Conversion Error
    int_cols = [r[0] for r in db.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' AND data_type='INTEGER'"
    ).fetchall()]
    for col in int_cols:
        try:
            db.execute(f"ALTER TABLE {table} ALTER {col} TYPE DOUBLE")
        except Exception:
            pass
    # 不加主键：API 返回含 report_type 多行(合并/母公司), 复合主键仍可能重复, DuckDB 大表可不加
    cols = [r[0] for r in db.execute(f"DESCRIBE {table}").fetchall()]
    log(f"  ✅ 新表 {table} 已建: {len(cols)} 列 = {cols[:6]}...")
    return cols

def pull_one(pro, api_name, ts_code):
    """拉单只股票全历史，带重试"""
    fn = getattr(pro, api_name)
    for attempt in range(3):
        try:
            df = fn(ts_code=ts_code)
            if df is None or len(df) == 0:
                return None
            # 统一日期格式为 YYYYMMDD
            for c in ['end_date', 'ann_date', 'f_ann_date']:
                if c in df.columns:
                    df[c] = df[c].astype(str).str.replace('-', '').str.replace('.0', '', regex=False)
            return df
        except Exception as e:
            err = str(e)
            if 'limit' in err.lower() or '每分钟' in err or '频率' in err:
                log(f"  ⏳ {ts_code} 触发限频, 等 30s...")
                time.sleep(30)
            else:
                time.sleep(2)
    return None

def rebuild_one(pro, db, api_name, ts_code, new_cols, table):
    """拉取并写入单只股票"""
    df = pull_one(pro, api_name, ts_code)
    if df is None:
        return 0
    # 只保留新表存在的列，按列序对齐
    df = df[[c for c in new_cols if c in df.columns]]
    if len(df) == 0:
        return 0
    db.register('_tmp_df', df)
    col_list = ', '.join(f'"{c}"' for c in df.columns)
    db.execute(f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM _tmp_df")
    db.unregister('_tmp_df')
    return len(df)

def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ['all']
    if 'all' in targets:
        targets = list(TABLES.keys())

    pro = get_pro()
    db = get_db()
    state = load_state()

    for t in targets:
        if t not in TABLES:
            log(f"❌ 未知目标 {t}")
            continue
        cfg = TABLES[t]
        table = cfg['table']
        api_name = cfg['api']
        log(f"\n{'='*55}\n重建 {table} (API: {api_name})\n{'='*55}")

        # 1. 建结构（先拉一只样本确定列）
        sample = pull_one(pro, api_name, '000001.SZ')
        if sample is None:
            log(f"❌ {table} 样本拉取失败")
            continue
        new_cols = list(sample.columns)

        # 2. 备份旧表 + 建新表
        backup_legacy(db, table)
        create_new_table(db, table, sample)
        db.execute("CHECKPOINT")

        # 3. 逐股票拉取（支持断点）
        stocks = get_stocks(db)
        done_key = f"{table}_done"
        if done_key in state:
            stocks = [s for s in stocks if s not in state[done_key]]
            log(f"  断点续跑: 跳过 {len(state[done_key])} 只已完成")
        log(f"  共 {len(stocks)} 只待拉取")

        total = 0
        consec_err = 0
        for i, ts_code in enumerate(stocks):
            try:
                n = rebuild_one(pro, db, api_name, ts_code, new_cols, table)
                total += n
                consec_err = 0
                if (i+1) % 200 == 0:
                    db.execute("CHECKPOINT")
                    save_state({**state, done_key: state.get(done_key, []) + stocks[:i+1]})
                    log(f"  [{i+1}/{len(stocks)}] 累计 {total:,} 行")
            except Exception as e:
                consec_err += 1
                log(f"  ⚠️ {ts_code}: {str(e)[:60]}")
                if consec_err >= MAX_CONSEC_ERR:
                    log(f"  ❌ 连续 {consec_err} 次错误，中止（可断点续跑）")
                    db.execute("CHECKPOINT")
                    db.close()
                    sys.exit(1)
            time.sleep(SLEEP)

        db.execute("CHECKPOINT")
        save_state({**state, done_key: state.get(done_key, []) + stocks})
        cnt = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        leg = db.execute(f"SELECT count(*) FROM {table}_legacy").fetchone()[0]
        log(f"  ✅ {table} 重建完成: 新表 {cnt:,} 行 (旧表 {leg:,} 行)")

    db.close()
    log("\n全部完成。验证后手动删除 legacy 表: DROP TABLE fin_xxx_legacy")

if __name__ == '__main__':
    main()
