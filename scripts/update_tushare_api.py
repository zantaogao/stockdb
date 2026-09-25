#!/usr/bin/env python3
"""
用 tushare API 增量更新 tushare.db
====================================
每个表只拉比本地最新的更晚的数据，断点续传。
拉到的数据写入数据库（UPSERT：按主键更新，不存在则插入）。
"""
import sys, json, os, time, warnings
from pathlib import Path
from datetime import datetime, timedelta

# 确保 stockdb 根目录在模块搜索路径中
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import tushare as ts
import duckdb
import pandas as pd

warnings.filterwarnings('ignore')

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'
TEMP_DB = BASE / 'tushare.db.new'
_ACTIVE_DB = TUSHARE_DB  # 原子交换模式下指向临时库
CONFIG = BASE / 'config.json'

# 每个 API 的每分钟调用限制
API_LIMITS = {
    'daily': 200,
    'daily_basic': 200,
    'adj_factor': 200,
    'stk_limit': 200,
    'moneyflow': 200,
    'index_daily': 50,
    'income': 100,
    'balancesheet': 100,
    'cashflow': 100,
    'stock_basic': 100,
}

def get_token():
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
        return cfg.get('tushare_token', '')
    except:
        return ''

def get_pro():
    token = get_token()
    if not token or token == 'YOUR_TOKEN':
        print("❌ 请先在 config.json 中设置 tushare_token")
        sys.exit(1)
    ts.set_token(token)
    return ts.pro_api()

def _safe_connect(path, read_only=False):
    """安全连接：连库 (不主动删 WAL),设 WAL 自动 checkpoint"""
    wal = str(path) + '.wal'
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        try:
            con.execute("SET wal_autocheckpoint = 100")
        except Exception:
            pass
    return con

def set_active_db(path):
    """切换当前写入目标（用于原子交换模式：写临时库）"""
    global _ACTIVE_DB
    _ACTIVE_DB = path

def get_db_readonly():
    return _safe_connect(_ACTIVE_DB, read_only=True)

def get_db_writable():
    return _safe_connect(_ACTIVE_DB)

def table_exists(db, name):
    return db.execute("""
        SELECT table_name FROM duckdb_tables() 
        WHERE table_name = ?
    """, [name]).fetchone() is not None

def next_day(ymd):
    """日历日 +1（2026-09-01 修复：str(int+1) 在月末跨月时产出非法日期，
    如 20260831+1=20260832，导致 stk_factor 上游重试对无效日期空转 3 分钟/天）。
    入参/返回均 YYYYMMDD 字符串。"""
    from datetime import datetime, timedelta
    return (datetime.strptime(str(ymd).replace('-', ''), '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')

def get_latest_date(db, table, date_col, where=None):
    """取表内最新日期。where 可选（如 'ts_code = ...' 按代码分别增量）。
    ⚠️ 返回值统一去横线（YYYYMMDD），避免表内混存横线/无横线两种格式时
    next_day(latest) 崩溃（2026-08-03 index_daily_raw 双格式陷阱）。"""
    try:
        sql = f"SELECT MAX({date_col}) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        r = db.execute(sql).fetchone()
        if r and r[0]:
            return str(r[0]).replace('-', '')
    except:
        pass
    return None

def upsert_df(db, df, table_name, if_exists='replace', where_col=None, where_val=None):
    """将 DataFrame 写入数据库，表不存在则创建，存在则替换
    DELETE + INSERT 包在显式事务里，异常自动回滚。
    where_col/where_val：可选，DELETE 时附加列过滤（如 ts_code），
    防止多代码循环写入时互相覆盖（2026-08-03 index_daily_raw 覆盖 bug 修复）。"""
    if df is None or len(df) == 0:
        return 0
    try:
        exists = table_exists(db, table_name)
        if exists:
            date_cols = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()]
            if date_cols:
                dc = date_cols[0]
                min_date = str(df[dc].min()).replace('-', '')
                max_date = str(df[dc].max()).replace('-', '')
                db.execute(f"BEGIN")
                try:
                    del_sql = f"DELETE FROM {table_name} WHERE {dc} >= ? AND {dc} <= ?"
                    del_params = [min_date, max_date]
                    if where_col and where_val is not None:
                        del_sql += f" AND {where_col} = ?"
                        del_params.append(where_val)
                    db.execute(del_sql, del_params)
                    db.execute(f"INSERT INTO {table_name} SELECT * FROM df")
                    db.execute("COMMIT")
                    extra = f" [{where_col}={where_val}]" if where_col else ""
                    print(f"    删除旧数据：{min_date}~{max_date}{extra}")
                except Exception as e_inner:
                    db.execute("ROLLBACK")
                    raise e_inner
            else:
                db.execute(f"INSERT INTO {table_name} SELECT * FROM df")
        else:
            db.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")
        return len(df)
    except Exception as e:
        print(f"    写入错误：{e}")
        return 0

def upsert_fin_df(db, df, table_name):
    """财报表专用写入：按 (ts_code, end_date) 精确删除再插入
    （财报表主键是 ts_code+end_date+report_type，不能用 ann_date 范围删）"""
    if df is None or len(df) == 0:
        return 0
    try:
        db.execute("BEGIN")
        for _, row in df.iterrows():
            tc = row['ts_code']
            ed = str(row['end_date'])[:10].replace('-', '')
            db.execute(f"DELETE FROM {table_name} WHERE ts_code=? AND end_date=?", [tc, ed])
        # 按列名显式插入（避免 SELECT * 列序问题）
        cols = list(df.columns)
        col_list = ', '.join(f'"{c}"' for c in cols)
        db.register('_fin_tmp', df)
        db.execute(f"INSERT INTO {table_name} ({col_list}) SELECT {col_list} FROM _fin_tmp")
        db.unregister('_fin_tmp')
        db.execute("COMMIT")
        return len(df)
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        print(f"    写入错误：{e}")
        return 0

def fetch_incremental(pro, func_name, df_func, table_name, date_col, start_date, end_date, **kwargs):
    """增量拉取：从 start_date 到 end_date，每次拉一天，写入数据库"""
    total = 0
    current = start_date
    while current <= end_date:
        try:
            df = df_func(**kwargs, **{date_col: current})
            if df is not None and len(df) > 0:
                written = upsert_df(db, df, table_name)
                total += written
                if written > 0:
                    print(f"    {current}: +{written} 条")
        except Exception as e:
            err_str = str(e)
            if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                print(f"    {current}: 达到 API 限制，跳过")
                break
            else:
                print(f"    {current}: {err_str[:60]}")
        current = next_day(current)
        time.sleep(0.15)
    return total

def update_index_daily(pro):
    print("\n=== 1. index_daily (指数日 K) ===")
    idx_codes = ['000001.SH', '000300.SH', '000016.SH', '000688.SH', 
                 '000905.SH', '399001.SZ', '399006.SZ', '399852.SZ', '899050.BJ',
                 '000852.SH']  # 2026-08-05: 加中证1000（策略账户市场基准）
    end_date = datetime.now().strftime('%Y%m%d')
    
    db = get_db_writable()
    try:
        total = 0
        # ⚠️ 2026-08-03 修复：必须按 ts_code 分别取最新日期做增量起点，
        # 不能用全表 MAX——899050.BJ（北证50，2026-07-27 才接入）会把全表
        # MAX 拉高，导致其他 8 个指数 start_date > end_date 永远跳过更新。
        for ts_code in idx_codes:
            try:
                latest = get_latest_date(db, 'index_daily_raw', 'trade_date', f"ts_code = '{ts_code}'")
                if not latest:
                    start_date = '20000101'
                else:
                    start_date = next_day(latest)
                if start_date > end_date:
                    print(f"  {ts_code}: 已是最新 ({latest})", flush=True)
                    continue
                df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and len(df) > 0:
                    # tushare 返回 df 格式: ts_code, trade_date, close, open, high, low, pre_close, change, pct_chg, vol, amount
                    # 去重写（带 ts_code 过滤，防止多指数循环互相覆盖）
                    written = upsert_df(db, df, 'index_daily_raw', where_col='ts_code', where_val=ts_code)
                    total += written
                    print(f"  {ts_code}: +{written} 条 ({start_date}~{end_date})", flush=True)
                else:
                    print(f"  {ts_code}: 无新数据 ({start_date}~{end_date})", flush=True)
            except Exception as e:
                print(f"  {ts_code}: {str(e)[:80]}", flush=True)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ index_daily: +{total} 条")

def update_daily(pro):
    print("\n=== 2. daily (日 K) ===")
    db = get_db_readonly()
    latest = get_latest_date(db, 'daily', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    db.close()
    
    if not latest:
        start_date = '20000101'
    else:
        start_date = next_day(latest)
    end_date = datetime.now().strftime('%Y%m%d')
    
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    db = get_db_writable()
    try:
        total = 0
        # 每天拉一次
        current = start_date
        while current <= end_date:
            try:
                df = pro.query('daily', trade_date=current)
                if df is not None and len(df) > 0:
                    written = upsert_df(db, df, 'daily')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制，等待 60 秒重试...")
                    time.sleep(65)
                    try:
                        df = pro.query('daily', trade_date=current)
                        if df is not None and len(df) > 0:
                            written = upsert_df(db, df, 'daily')
                            total += written
                            print(f"  {current} (重试): +{written} 条")
                    except Exception as e2:
                        print(f"  {current}: 重试失败：{e2}")
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.12)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ daily: +{total} 条")

def update_daily_basic(pro):
    print("\n=== 3. daily_basic (每日指标) ===")
    db = get_db_readonly()
    latest = get_latest_date(db, 'daily_basic', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    db.close()
    
    if not latest:
        start_date = '20000101'
    else:
        start_date = next_day(latest)
    end_date = datetime.now().strftime('%Y%m%d')
    
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    db = get_db_writable()
    try:
        total = 0
        current = start_date
        while current <= end_date:
            try:
                df = pro.daily_basic(trade_date=current)
                if df is not None and len(df) > 0:
                    written = upsert_df(db, df, 'daily_basic')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制")
                    break
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.15)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ daily_basic: +{total} 条")

def update_adj_factor(pro):
    print("\n=== 4. adj_factor (复权因子) ===")
    db = get_db_readonly()
    latest = get_latest_date(db, 'adj_factor', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    db.close()
    
    if not latest:
        start_date = '20000101'
    else:
        start_date = next_day(latest)
    end_date = datetime.now().strftime('%Y%m%d')
    
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    db = get_db_writable()
    try:
        total = 0
        current = start_date
        while current <= end_date:
            try:
                df = pro.adj_factor(start_date=current, end_date=current)
                if df is not None and len(df) > 0:
                    written = upsert_df(db, df, 'adj_factor')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制")
                    break
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.15)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ adj_factor: +{total} 条")

def update_fin_income(pro):
    print("\n=== 5. fin_income (利润表) ===")
    db = get_db_readonly()
    latest_end = get_latest_date(db, 'fin_income', 'end_date')
    print(f"  本地最新 end_date: {latest_end or '无'}")
    
    # 获取股票列表（用已有只读连接）
    stocks = db.execute("SELECT ts_code FROM stock_basic").fetchall()
    db.close()
    
    # 列集兼容性检查（2026-08-31 修）：旧守卫用 INSERT OR REPLACE 探测，
    # 但 08-01 财报三表重建后无 PK/UNIQUE → 必报 "no UNIQUE/PRIMARY KEY constraints"
    # Binder Error，被误判成"表结构不匹配"（实为误杀，85 列完全匹配）。
    # 真实写入路径 upsert_fin_df 是显式 DELETE+列名 INSERT，不需要主键，
    # 所以守卫改为直接比对本地列集 vs API 列集。
    try:
        test_df = pro.income(ts_code='000001.SZ', start_date='20260101', end_date='20260331')
    except Exception as e:
        print(f"  ⚠️ fin_income 探测拉取失败: {str(e)[:80]}，跳过本轮更新")
        return 0
    if test_df is not None and len(test_df) > 0:
        try:
            _ro = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
            local_cols = {r[0] for r in _ro.execute("DESCRIBE fin_income").fetchall()}
            _ro.close()
            missing = sorted(set(test_df.columns) - local_cols)
            if missing:
                print(f"  ⚠️ fin_income 表结构不匹配 (API返回{len(test_df.columns)}列, 本地缺: {missing})")
                print(f"  ⚠️ 跳过 fin_income 更新，表结构需手动修复")
                return 0
        except Exception as e:
            print(f"  ⚠️ fin_income 列集检查失败: {str(e)[:80]}，跳过本轮更新")
            return 0
    
    if not stocks:
        print("  ⚠️ stock_basic 为空，先更新 stock_basic")
        return 0
    
    # 2026-08-31：守卫修复后 fin_income 恢复更新，挂上与 balancesheet/cashflow
    # 同款 7 天节流戳，防止每日 5890 只逐拉把写锁拖过 16:10 引发下游 BlockingIOError
    _stamp = BASE / '.fin_last_update'
    try:
        if _stamp.exists():
            _last = _stamp.read_text().strip()
            if _last:
                _gap = (datetime.now() - datetime.strptime(_last, '%Y%m%d')).days
                if _gap < 7:
                    print(f"  fin 表 7 天内已拉取（{_last}，距今 {_gap} 天），跳过逐只拉取（2026-08-31 节流）")
                    return 0
    except Exception:
        pass
    
    print(f"  共 {len(stocks)} 只股票，分批更新（每批500只）")
    
    db = get_db_writable()
    try:
        total = 0
        n_changed = 0
        err_kinds = {}
        start_date = '20000101' if not latest_end else latest_end
        end_date = '20261231'
        
        batch_size = 500
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i+batch_size]
            for (ts_code,) in batch:
                try:
                    df = pro.income(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if df is not None and len(df) > 0:
                        written = upsert_fin_df(db, df, 'fin_income')
                        total += written
                        if written > 0:
                            n_changed += 1  # 2026-08-31 聚合打印：避免 5890 行明细撑爆 cron stdout
                except Exception as e:
                    err_str = str(e)[:60]
                    # 静默跳过列不匹配的，不逐个打印 5872 次
                    if 'Binder Error' not in err_str:
                        err_kinds[err_str[:40]] = err_kinds.get(err_str[:40], 0) + 1
            print(f"  批次 {i//batch_size+1}/{(len(stocks)-1)//batch_size+1}: 已更新 {total} 条（{n_changed} 只股票有变更）")
        
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ fin_income: +{total} 条（{n_changed} 只股票有变更）" + (f" | 错误: {err_kinds}" if err_kinds else ""))

def update_fin_balancesheet(pro):
    print("\n=== 6. fin_balancesheet (资产负债表) ===")
    db = get_db_readonly()
    latest_end = get_latest_date(db, 'fin_balancesheet', 'end_date')
    print(f"  本地最新 end_date: {latest_end or '无'}")
    
    # 获取股票列表
    stocks = db.execute("SELECT ts_code FROM stock_basic").fetchall()
    db.close()
    
    if not stocks:
        print("  ⚠️ stock_basic 为空")
        return 0
    
    print(f"  共 {len(stocks)} 只股票")
    
    # 2026-08-10 优化：财报逐只拉取（5878 只×2 接口）是更新 40 分钟耗时主因。
    # 改为 7 天间隔低频刷新（新报告期最多延迟 7 天，fin 特征季度级变化影响极小）。
    _stamp = BASE / '.fin_last_update'
    try:
        if _stamp.exists():
            _last = _stamp.read_text().strip()
            if _last:
                _gap = (datetime.now() - datetime.strptime(_last, '%Y%m%d')).days
                if _gap < 7:
                    print(f"  fin 表 7 天内已拉取（{_last}，距今 {_gap} 天），跳过逐只拉取（2026-08-10 优化）")
                    return 0
    except Exception:
        pass
    
    db = get_db_writable()
    try:
        total = 0
        n_changed = 0
        err_kinds = {}
        start_date = '20000101' if not latest_end else latest_end
        end_date = '20261231'
        
        for (ts_code,) in stocks:
            try:
                df = pro.balancesheet(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and len(df) > 0:
                    written = upsert_fin_df(db, df, 'fin_balancesheet')
                    total += written
                    if written > 0:
                        n_changed += 1  # 2026-08-31 聚合打印：5890 行明细会撑爆 cron stdout（180s 超时）
            except Exception as e:
                _k = str(e)[:40]
                err_kinds[_k] = err_kinds.get(_k, 0) + 1
        
        db.execute("CHECKPOINT")
    finally:
        db.close()
    try:
        _stamp.write_text(datetime.now().strftime('%Y%m%d'))
    except Exception:
        pass
    print(f"  ✅ fin_balancesheet: +{total} 条（{n_changed} 只股票有变更）" + (f" | 错误: {err_kinds}" if err_kinds else ""))

def update_fin_cashflow(pro):
    print("\n=== 7. fin_cashflow (现金流量表) ===")
    db = get_db_readonly()
    latest_end = get_latest_date(db, 'fin_cashflow', 'end_date')
    print(f"  本地最新 end_date: {latest_end or '无'}")
    
    # 获取股票列表
    stocks = db.execute("SELECT ts_code FROM stock_basic").fetchall()
    db.close()
    
    if not stocks:
        print("  ⚠️ stock_basic 为空")
        return 0
    
    print(f"  共 {len(stocks)} 只股票")
    
    # 2026-08-10 优化：同 fin_balancesheet，7 天间隔低频刷新
    _stamp = BASE / '.fin_last_update'
    try:
        if _stamp.exists():
            _last = _stamp.read_text().strip()
            if _last:
                _gap = (datetime.now() - datetime.strptime(_last, '%Y%m%d')).days
                if _gap < 7:
                    print(f"  fin 表 7 天内已拉取（{_last}，距今 {_gap} 天），跳过逐只拉取（2026-08-10 优化）")
                    return 0
    except Exception:
        pass
    
    db = get_db_writable()
    try:
        total = 0
        n_changed = 0
        err_kinds = {}
        start_date = '20000101' if not latest_end else latest_end
        end_date = '20261231'
        
        for (ts_code,) in stocks:
            try:
                df = pro.cashflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and len(df) > 0:
                    written = upsert_fin_df(db, df, 'fin_cashflow')
                    total += written
                    if written > 0:
                        n_changed += 1  # 2026-08-31 聚合打印：同 fin_balancesheet
            except Exception as e:
                _k = str(e)[:40]
                err_kinds[_k] = err_kinds.get(_k, 0) + 1
        
        db.execute("CHECKPOINT")
    finally:
        db.close()
    try:
        _stamp.write_text(datetime.now().strftime('%Y%m%d'))
    except Exception:
        pass
    print(f"  ✅ fin_cashflow: +{total} 条（{n_changed} 只股票有变更）" + (f" | 错误: {err_kinds}" if err_kinds else ""))

def update_stk_limit(pro):
    print("\n=== 8. stk_limit (涨跌停) ===")
    db = get_db_readonly()
    latest = get_latest_date(db, 'stk_limit', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    db.close()
    
    if not latest:
        start_date = '20150101'
    else:
        start_date = next_day(latest)
    end_date = datetime.now().strftime('%Y%m%d')
    
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    db = get_db_writable()
    try:
        total = 0
        current = start_date
        while current <= end_date:
            try:
                df = pro.query('stk_limit', trade_date=current)
                if df is not None and len(df) > 0:
                    written = upsert_df(db, df, 'stk_limit')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制")
                    break
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.15)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ stk_limit: +{total} 条")

def update_moneyflow(pro):
    print("\n=== 9. moneyflow (资金流) ===")
    db = get_db_readonly()
    latest = get_latest_date(db, 'moneyflow_raw', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    db.close()
    
    if not latest:
        start_date = '20100101'
    else:
        start_date = next_day(latest)
    end_date = datetime.now().strftime('%Y%m%d')
    
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    db = get_db_writable()
    try:
        total = 0
        current = start_date
        while current <= end_date:
            try:
                df = pro.query('moneyflow', trade_date=current)
                if df is not None and len(df) > 0:
                    written = upsert_df(db, df, 'moneyflow_raw')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制，等待 60 秒重试...")
                    time.sleep(65)
                    try:
                        df = pro.query('moneyflow', trade_date=current)
                        if df is not None and len(df) > 0:
                            written = upsert_df(db, df, 'moneyflow_raw')
                            total += written
                            print(f"  {current} (重试): +{written} 条")
                    except Exception as e2:
                        print(f"  {current}: 重试失败：{e2}")
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.12)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ moneyflow: +{total} 条")

def update_stk_factor(pro):
    """更新旧 stk_factor 表（25列 + extra JSON）
    数据源：stk_factor_pro 接口（与 M2 pull_tushare_factors.py 同构）
    extra: 接口返回中非 core 列的其余因子（open_/high_/low_/close_/pre_close_ 前缀除外）
    """
    print("\n=== 10b. stk_factor (旧表, 25列+extra JSON) ===")
    
    db = get_db_readonly()
    if not table_exists(db, 'stk_factor'):
        print("  ⚠️ 表 stk_factor 不存在，跳过")
        db.close()
        return 0
    
    latest = get_latest_date(db, 'stk_factor', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    
    if not latest:
        earliest = db.execute('SELECT MIN(trade_date) FROM daily').fetchone()[0]
        start_date = earliest or '20050104'
    else:
        start_date = next_day(latest)
    db.close()
    
    end_date = datetime.now().strftime('%Y%m%d')
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    core_cols = ['ts_code','trade_date','open','high','low','close','pre_close',
                 'change','pct_chg','vol','amount',
                 'macd_dif','macd_dea','macd','kdj_k','kdj_d','kdj_j',
                 'rsi_6','rsi_12','rsi_24',
                 'boll_upper','boll_mid','boll_lower','cci']
    # 表结构列序：ts_code, trade_date 在前，其余 core 列，最后 extra
    insert_cols = ['ts_code','trade_date'] + core_cols[2:] + ['extra']
    
    db = get_db_writable()
    try:
        total = 0
        current = start_date
        while current <= end_date:
            try:
                # 2026-08-08 上游延迟重试: stk_factor_pro 当天因子 tushare 端可能未算完
                # (08-07 实盘: 16:00 返回空 → 08-07 0 行 → 周末信号用滞后1天因子)。
                # 空或行数<5000(未算完, 与缺口回补同阈值)时等待 60s 重试, 最多 3 次。
                df = pro.stk_factor_pro(trade_date=current)
                for _retry in range(3):
                    if df is not None and len(df) >= 5000:
                        break
                    print(f"  {current}: 上游未算完({0 if df is None else len(df)} 行), 60s 后重试 {_retry+1}/3...")
                    time.sleep(60)
                    df = pro.stk_factor_pro(trade_date=current)
                if df is not None and len(df) > 0:
                    # 构建 25列 + extra JSON（对齐 M2 pull_tushare_factors.py 逻辑）
                    rows_list = []
                    for _, row in df.iterrows():
                        r = {}
                        r['ts_code'] = row['ts_code']
                        r['trade_date'] = str(row['trade_date'])[:10].replace('-', '')
                        for k in core_cols[2:]:
                            v = row.get(k)
                            r[k] = float(v) if v is not None else 0.0
                        extra = {}
                        for k in row.index:
                            if k in ('ts_code','trade_date') or k.startswith(('open_','high_','low_','close_','pre_close')):
                                continue
                            if k in core_cols:
                                continue
                            v = row[k]
                            if v is not None:
                                extra[k] = round(float(v), 4) if isinstance(v, (int, float)) else str(v)
                        r['extra'] = json.dumps(extra, ensure_ascii=False)
                        rows_list.append(r)
                    
                    import pandas as pd
                    pdf = pd.DataFrame(rows_list)[insert_cols]
                    written = upsert_df(db, pdf, 'stk_factor')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制，等待 60 秒重试...")
                    time.sleep(65)
                    try:
                        df = pro.stk_factor_pro(trade_date=current)
                        if df is not None and len(df) > 0:
                            rows_list = []
                            for _, row in df.iterrows():
                                r = {}
                                r['ts_code'] = row['ts_code']
                                r['trade_date'] = str(row['trade_date'])[:10].replace('-', '')
                                for k in core_cols[2:]:
                                    v = row.get(k)
                                    r[k] = float(v) if v is not None else 0.0
                                extra = {}
                                for k in row.index:
                                    if k in ('ts_code','trade_date') or k.startswith(('open_','high_','low_','close_','pre_close')):
                                        continue
                                    if k in core_cols:
                                        continue
                                    v = row[k]
                                    if v is not None:
                                        extra[k] = round(float(v), 4) if isinstance(v, (int, float)) else str(v)
                                r['extra'] = json.dumps(extra, ensure_ascii=False)
                                rows_list.append(r)
                            import pandas as pd
                            pdf = pd.DataFrame(rows_list)[insert_cols]
                            written = upsert_df(db, pdf, 'stk_factor')
                            total += written
                            print(f"  {current} (重试): +{written} 条")
                    except Exception as e2:
                        print(f"  {current}: 重试失败：{e2}")
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.12)

        # ── 缺口回补 (2026-08-04 新增): 按 daily 交易日历检查, 行数<5000的日期重拉 ──
        # 背景: 08-03 tushare端当天未算完只返回1367行, 08-04 0行; 增量逻辑从不回补→缺口残留。
        # 次日再跑时 tushare 端已全量, 此处幂等 upsert 自动补全。用 daily 做交易日历,
        # 覆盖"当日无任何行"的完全缺失 (GROUP BY 查不到行=漏判)。
        try:
            cutoff = (datetime.now() - timedelta(days=14)).strftime('%Y%m%d')
            # ⚠️ 2026-08-05 修复：不能再用 get_db_readonly()——主循环的 db(可写) 已连着 TEMP_DB，
            # DuckDB 不允许同文件同时开不同 read_only 配置的连接 → "Connection Error: Can't open a connection
            # to same database file with a different..." → 缺口回补从 8/4 加进来从未成功（8/3 一直缺）。
            # 直接复用 db（同一可写连接）。
            trading_days = [r[0] for r in db.execute(
                "SELECT DISTINCT trade_date FROM daily WHERE trade_date >= ? ORDER BY trade_date",
                (cutoff,)).fetchall()]
            for rdate in trading_days:
                n = db.execute(
                    "SELECT COUNT(*) FROM stk_factor WHERE trade_date = ?", (rdate,)).fetchone()[0]
                if n >= 5000:
                    continue
                print(f"  ⚠️ {rdate} 行数异常 ({n} < 5000), 回补拉取...")
                try:
                    import pandas as pd  # 2026-08-05: 函数内其他 import 使其成局部变量，此处必须显式 import
                    # 2026-08-08 回补重试: 拉取后仍 <5000(上游未算完)时等待 60s 重试, 最多 2 次
                    df = pro.stk_factor_pro(trade_date=rdate)
                    for _retry in range(2):
                        if df is not None and len(df) >= 5000:
                            break
                        print(f"  {rdate}: 回补上游未算完({0 if df is None else len(df)} 行), 60s 后重试 {_retry+1}/2...")
                        time.sleep(60)
                        df = pro.stk_factor_pro(trade_date=rdate)
                    if df is not None and len(df) > 0:
                        rows_list = []
                        for _, row in df.iterrows():
                            r = {}
                            r['ts_code'] = row['ts_code']
                            r['trade_date'] = str(row['trade_date'])[:10].replace('-', '')
                            for k in core_cols[2:]:
                                v = row.get(k)
                                r[k] = float(v) if v is not None else 0.0
                            extra = {}
                            for k in row.index:
                                if k in ('ts_code','trade_date') or k.startswith(('open_','high_','low_','close_','pre_close')):
                                    continue
                                if k in core_cols:
                                    continue
                                v = row[k]
                                if v is not None:
                                    extra[k] = round(float(v), 4) if isinstance(v, (int, float)) else str(v)
                            r['extra'] = json.dumps(extra, ensure_ascii=False)
                            rows_list.append(r)
                        pdf = pd.DataFrame(rows_list)[insert_cols]
                        written = upsert_df(db, pdf, 'stk_factor')
                        total += written
                        print(f"  {rdate} 回补完成: +{written} 条")
                except Exception as e:
                    print(f"  {rdate} 回补失败: {str(e)[:80]}")
        except Exception as e:
            print(f"  ⚠️ 缺口回补检查失败: {str(e)[:80]}")

        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ stk_factor: +{total} 条")

def update_stk_factor_pro(pro):
    """更新技术指标因子（stk_factor_pro）"""
    print("\n=== 10. stk_factor_pro (技术指标因子) ===")
    
    db = get_db_readonly()
    
    # 检查表是否存在
    if not table_exists(db, 'stk_factor_pro'):
        print("  ⚠️ 表 stk_factor_pro 不存在，跳过（或手动创建）")
        db.close()
        return 0
    
    latest = get_latest_date(db, 'stk_factor_pro', 'trade_date')
    print(f"  本地最新：{latest or '无'}")
    
    if not latest:
        # 首次全量：从 daily 最早日期开始
        earliest = db.execute('SELECT MIN(trade_date) FROM daily').fetchone()[0]
        start_date = earliest or '20050104'
    else:
        start_date = next_day(latest)
    
    db.close()
    
    end_date = datetime.now().strftime('%Y%m%d')
    
    if start_date > end_date:
        print("  ✅ 已是最新")
        return 0
    
    db = get_db_writable()
    try:
        total = 0
        current = start_date
        while current <= end_date:
            try:
                df = pro.stk_factor_pro(trade_date=current)
                if df is not None and len(df) > 0:
                    written = upsert_df(db, df, 'stk_factor_pro')
                    total += written
                    if written > 0:
                        print(f"  {current}: +{written} 条")
            except Exception as e:
                err_str = str(e)
                if 'limit' in err_str.lower() or 'reach' in err_str.lower():
                    print(f"  {current}: 达到 API 限制，等待 60 秒重试...")
                    time.sleep(65)
                    try:
                        df = pro.stk_factor_pro(trade_date=current)
                        if df is not None and len(df) > 0:
                            written = upsert_df(db, df, 'stk_factor_pro')
                            total += written
                            print(f"  {current} (重试): +{written} 条")
                    except Exception as e2:
                        print(f"  {current}: 重试失败：{e2}")
                else:
                    print(f"  {current}: {err_str[:60]}")
            current = next_day(current)
            time.sleep(0.12)
        db.execute("CHECKPOINT")
    finally:
        db.close()
    print(f"  ✅ stk_factor_pro: +{total} 条")

def update_stock_basic(pro):
    print("\n=== 0. stock_basic (股票列表) ===")
    db = get_db_readonly()
    cnt = db.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
    print(f"  本地：{cnt} 只")
    db.close()
    
    db = get_db_writable()
    try:
        # 获取表结构，按列名请求对应字段
        existing_cols = [c[0] for c in db.execute("DESCRIBE stock_basic").fetchall()]
        if not existing_cols:
            existing_cols = None

        # 先清空再全量写入，包在事务里
        db.execute("BEGIN")
        db.execute("DELETE FROM stock_basic")
        total = 0
        for status in ['L', 'D', 'P']:
            label = {'L': '上市', 'D': '终止', 'P': '待上市'}[status]
            try:
                if existing_cols:
                    fields = ','.join(existing_cols)
                    df = pro.stock_basic(exchange='', list_status=status, fields=fields)
                else:
                    fields = 'ts_code,name,market,list_date'
                    df = pro.stock_basic(exchange='', list_status=status, fields=fields)
                if df is not None and len(df) > 0:
                    db.execute("INSERT INTO stock_basic SELECT * FROM df")
                    total += len(df)
                    print(f"  {label}: {len(df)} 只")
            except Exception as e:
                print(f"  {label}: 错误 {e}")
        db.execute("COMMIT")
        db.execute("CHECKPOINT")
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        print(f"  写入失败：{e}")
    finally:
        db.close()
    print(f"  ✅ stock_basic: 共 {total} 条")





def update_etf(pro):
    """更新 ETF 数据（fund_basic + fund_daily）"""
    print("\n=== 11. ETF (基金数据) ===")
    db = get_db_readonly()
    db.execute("CREATE TABLE IF NOT EXISTS fund_basic (ts_code VARCHAR PRIMARY KEY, name VARCHAR, fund_type VARCHAR, list_date VARCHAR, found_date VARCHAR, market VARCHAR, invest_type VARCHAR)")
    db.execute("CREATE TABLE IF NOT EXISTS fund_daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE, PRIMARY KEY (ts_code, trade_date))")
    db.close()
    dbw = get_db_writable()
    try:
        print("  拉取 ETF 列表...")
        df = pro.fund_basic(market="E")
        if df is not None and len(df) > 0:
            keep = ["ts_code","name","fund_type","list_date","found_date","market","invest_type"]
            keep = [c for c in keep if c in df.columns]
            upsert_df(dbw, df[keep], 'fund_basic')
        codes = [r[0] for r in dbw.execute("SELECT ts_code FROM fund_basic WHERE list_date IS NOT NULL").fetchall()]
        print(f"  待拉净值: {len(codes)} 只 ETF", flush=True)
        total = 0
        for c in codes:
            try:
                latest = dbw.execute("SELECT MAX(trade_date) FROM fund_daily WHERE ts_code=?", [c]).fetchone()[0]
                start = str(next_day(latest)) if latest else '20250101'
                end = __import__('datetime').datetime.now().strftime('%Y%m%d')
                if start > end: continue
                df2 = pro.fund_daily(ts_code=c, start_date=start, end_date=end)
                if df2 is not None and len(df2) > 0:
                    dbw.execute('DELETE FROM fund_daily WHERE ts_code=? AND trade_date>=?', (c, start))
                    for _, row in df2.iterrows():
                        dbw.execute('INSERT OR REPLACE INTO fund_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            (row['ts_code'], str(row['trade_date']), float(row.get('open',0)), float(row.get('high',0)), float(row.get('low',0)), float(row.get('close',0)), float(row.get('pre_close',0)), float(row.get('change',0)), float(row.get('pct_chg',0)), float(row.get('vol',0)), float(row.get('amount',0))))
                        total += 1
            except Exception as e:
                if 'limit' in str(e).lower():
                    import time; time.sleep(65)
        dbw.execute('CHECKPOINT')
        print(f'  fund_daily: +{total} 条')
    finally:
        dbw.close()
    print('  ✅ ETF 更新完成')
def main():
    # 分相看门狗（09-14 事故：一刀切40min把"拉取完成、只差校验换库"的正常进程杀在换库前）
    from core.db_lock import PhasedWatchdog
    _wd = PhasedWatchdog(label='update_tushare_api')
    _wd.enter_phase(40, '拉取+写入')  # 原25太紧(09-07财报12批慢速被误杀)保持40
    # 加写锁：更新期间禁止其他进程操作
    from core.db_lock import tushare_write_lock
    with tushare_write_lock(timeout=600):
        print("=" * 60)
        print("Tushare API 增量更新（原子写入）")
        print("=" * 60)
        
        pro = get_pro()
        print(f"  ✅ tushare API 连接成功")
    
        # ── 1. 克隆活库 → 临时库（APFS CoW，瞬间完成）──
        if TEMP_DB.exists():
            print("  ⚠️ 清理残留临时库")
            TEMP_DB.unlink()
        _tmp_wal = Path(str(TEMP_DB) + '.wal')
        if _tmp_wal.exists():
            # 2026-08-24 事故：16:00 更新中途被杀留下损坏 .new.wal，
            # 下次克隆后 DuckDB replay 该 WAL 直接 Corrupt 失败 → 必须一并清理
            print(f"  ⚠️ 清理残留临时库 WAL: {_tmp_wal.name}")
            _tmp_wal.unlink()
        
        # 2026-08-24 加固：克隆前必须先 CHECKPOINT 活库，把 WAL 合并进主文件——
        # 否则 cp -c / clonefile 只复制主文件，WAL 里的未合并数据会丢（活库 wal 存在的隐患）。
        try:
            vc = duckdb.connect(str(TUSHARE_DB), read_only=False)
            vc.execute("CHECKPOINT")
            vc.close()
            print("  ✅ 活库 CHECKPOINT 完成（WAL 已合并）")
        except Exception as e:
            print(f"  ⚠️ 活库 CHECKPOINT 失败（继续，WAL 未合并风险）: {str(e)[:100]}")
        
        # cp -c（BSD cp 的 APFS 克隆，CoW 秒级且不占双份空间）优先；
        # os.clonefile 在本机 Python 不可用（hasattr=False，2026-08-24 实测），
        # copy2 全量复制 65G 会占双份空间 → 磁盘爆掉根因，仅作最后 fallback。
        import subprocess as _sp
        _clone_ok = False
        try:
            _r = _sp.run(['cp', '-c', str(TUSHARE_DB), str(TEMP_DB)], capture_output=True, timeout=120)
            if _r.returncode == 0:
                _clone_ok = True
                print("  ✅ 克隆到临时库 (APFS CoW cp -c，秒级)")
            else:
                print(f"  ⚠️ cp -c 失败({_r.returncode})，fallback copy2: {_r.stderr.decode()[:100]}")
        except Exception as e:
            print(f"  ⚠️ cp -c 异常，fallback copy2: {str(e)[:100]}")
        if not _clone_ok:
            import shutil
            shutil.copy2(str(TUSHARE_DB), str(TEMP_DB))
            sz = TEMP_DB.stat().st_size
            print(f"  ✅ 复制到临时库 ({sz/1e9:.1f}GB) — 注意：copy2 占双份空间，磁盘需 ≥{sz/1e9*2:.0f}G 可用")
        
        # ── 2. 切换写入目标到临时库 ──
        set_active_db(TEMP_DB)
        print(f"  ✅ 写入目标已切换到临时库")
    
        # ── 3. 备份活库（原始文件，更新前状态；2026-08-24 改 cp -c CoW 不占双份空间）──
        bak_local = str(TUSHARE_DB) + '.bak.local'
        if os.path.exists(str(TUSHARE_DB)):
            try:
                _r = _sp.run(['cp', '-c', str(TUSHARE_DB), bak_local], capture_output=True, timeout=120)
                if _r.returncode == 0:
                    print(f"  ✅ 已备份到 {bak_local} (APFS CoW)")
                else:
                    raise RuntimeError(_r.stderr.decode()[:100])
            except Exception as e:
                import shutil
                try:
                    shutil.copy2(str(TUSHARE_DB), bak_local)
                    print(f"  ✅ 已备份到 {bak_local} (copy2 fallback)")
                except Exception as e2:
                    print(f"  ⚠️ 备份失败（不阻断更新）: {e2}")
        else:
            print("  ⚠️ tushare.db 不存在，跳过备份")
        
        # ── 4. 更新临时库（所有 gets/sets 指向 TEMP_DB）──
        update_stock_basic(pro)
        update_index_daily(pro)
        update_daily(pro)
        update_daily_basic(pro)
        update_adj_factor(pro)
        # 财报三表（2026-08-01 重建为 API 完整版后已解除跳过）
        update_fin_income(pro)
        update_fin_balancesheet(pro)
        update_fin_cashflow(pro)
        update_stk_limit(pro)
        update_moneyflow(pro)
        update_stk_factor_pro(pro)
        update_stk_factor(pro)
        # 新增表按需启用
        # update_monthly(pro)
        # update_weekly(pro)
        # update_stock_valuation(pro)
        
        # ── 5. 验证临时库完整性（全表强读，触发所有 block 的 checksum 校验）──
        # 09-14 事故修复：拉取+写入到此已全部落盘，换独立限时相位
        _wd.enter_phase(60, '强读校验+促升')
        print("\n--- 验证临时库（全表强读）---")
        try:
            # 5.0 先 CHECKPOINT，确保 WAL 合并进主文件（否则 os.replace 会丢 WAL 数据）
            vc = duckdb.connect(str(TEMP_DB), read_only=False)
            vc.execute("CHECKPOINT")
            vc.close()
            wal_file = str(TEMP_DB) + '.wal'
            if os.path.exists(wal_file) and os.path.getsize(wal_file) > 0:
                raise Exception(f"WAL 未清空: {wal_file} ({os.path.getsize(wal_file)}B)")

            # 5.1 全表强读：流式读取每张物理表的全部数据，逐块校验 checksum
            vc = duckdb.connect(str(TEMP_DB), read_only=True)
            vtables = vc.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name"
            ).fetchall()
            total_rows = 0
            for (vt,) in vtables:
                cur = vc.cursor()
                cur.execute(f'SELECT * FROM "{vt}"')
                cnt = 0
                while True:
                    batch = cur.fetchmany(50000)
                    if not batch:
                        break
                    cnt += len(batch)
                cur.close()
                total_rows += cnt
                print(f"  {vt}: {cnt:,} rows ✅")
            vc.close()
            print(f"  ✅ 临时库校验通过（{len(vtables)} 表, {total_rows:,} 行）")
        except Exception as e:
            print(f"  ❌ 临时库校验失败：{e}")
            print("  ⚠️ 放弃本次更新，活库不受影响")
            if TEMP_DB.exists():
                TEMP_DB.unlink()
            set_active_db(TUSHARE_DB)
            return

        # ── 6. 原子交换：临时库 → 活库（交换后立即复验，失败自动回滚）──
        os.replace(str(TEMP_DB), str(TUSHARE_DB))
        set_active_db(TUSHARE_DB)
        print("  ✅ 原子交换完成，复验活库...")
        try:
            vc = duckdb.connect(str(TUSHARE_DB), read_only=True)
            vtables = vc.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name"
            ).fetchall()
            for (vt,) in vtables:
                cur = vc.cursor()
                cur.execute(f'SELECT * FROM "{vt}"')
                while True:
                    batch = cur.fetchmany(50000)
                    if not batch:
                        break
                cur.close()
                print(f"  {vt} ✅")
            vc.close()
            print("  ✅ 活库复验通过")
        except Exception as e:
            print(f"  ❌ 活库复验失败：{e}")
            print("  ⚠️ 从 bak.local 自动回滚...")
            import shutil
            shutil.copy2(bak_local, str(TUSHARE_DB))
            set_active_db(TUSHARE_DB)
            print("  ✅ 已从 bak.local 回滚")
            return
    
        # ── 7. 删除旧本地备份 ──
        old_bak = str(TUSHARE_DB) + '.bak'
        if os.path.exists(old_bak):
            os.remove(old_bak)

    # 验证活库
    _wd.enter_phase(45, '收尾状态显示')  # 锁外全表COUNT仅为展示，独立限时防其卡死拖住退出
    print("\n" + "=" * 60)
    print("验证 tushare.db 状态")
    print("=" * 60)
    db = get_db_readonly()
    try:
        tables = db.execute('SHOW TABLES').fetchall()
        for t in tables:
            try:
                cnt = db.execute('SELECT COUNT(*) FROM ' + t[0]).fetchone()[0]
                cols = db.execute('PRAGMA table_info(' + t[0] + ')').fetchall()
                dc = [c[1] for c in cols if 'date' in c[1].lower()]
                if dc:
                    latest = db.execute('SELECT MAX(' + dc[0] + ') FROM ' + t[0]).fetchone()[0]
                    print(f"  {t[0]:25s} {cnt:>12,} rows  latest={latest}")
                else:
                    print(f"  {t[0]:25s} {cnt:>12,} rows")
            except Exception as e:
                print(f"  {t[0]:25s} ERROR: {e}")
    finally:
        db.close()
    print("\n✅ 完成")
 
if __name__ == '__main__':
    # 09-14: 一刀切start_hard_watchdog(40)改为main()内PhasedWatchdog分相限时
    main()
