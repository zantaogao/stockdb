"""
统一DB连接(DuckDB) — 防损坏优化版
=====================================
每次调用新建连接,无全局缓存,线程安全.

防护机制：
1. 内存限制(SET memory_limit='32GB') 防 OOM 崩溃
2. 线程数限制(SET threads=4) 降低并发压力
3. 临时目录隔离(temp_directory) 避免 spill 污染库文件
4. 只读模式严格化(read_only=True)
5. 连接失败时自动重试（清理WAL后重连）
6. **不主动删 WAL** — 删除 WAL 会丢失崩溃恢复数据

铁律：除了 API 自动更新脚本,其他全部只读.
所有业务记录必须写入 v2 三层: 账本→ledger.db(热) / 信号→signals.db(温) / 因子归档→factors.db(冷). state.db 已冻结.
"""
import duckdb
import os
import time
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'

# --- 主力库定义 ---
TUSHARE_DB_PATH = BASE / 'tushare.db'

# DuckDB 稳定化设置
_DUCKDB_SETTINGS = {
    'memory_limit': '32GB',
    'threads': 4,
    'temp_directory': '/tmp/duckdb_tmp',
}


def _ensure_tmp_dir():
    """确保临时目录存在"""
    tmp = Path('/tmp/duckdb_tmp')
    tmp.mkdir(parents=True, exist_ok=True)


def _clean_wal(path):
    """仅用于恢复时清理 WAL — 正常连接不删 WAL"""
    for suffix in ('.wal', '.shm'):
        f = str(path) + suffix
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass


def _apply_stable_settings(con):
    """应用 DuckDB 稳定化设置—防 OOM/防 WAL 膨胀"""
    for key, val in _DUCKDB_SETTINGS.items():
        try:
            con.execute(f"SET {key} = '{val}'")
        except Exception:
            pass


def _safe_connect(path, read_only=True, retry=1):
    """安全连接：连库 → 应用稳定设置

    关键变动：不再主动删除 WAL。WAL 是崩溃恢复的关键，
    删了会导致数据不一致。只在 checksum 校验失败时
    才清理 WAL 重试。

    Args:
        path: 数据库路径
        read_only: 是否只读
        retry: 连接失败重试次数（WAL损坏时清理后重试）
    """
    from .db_lock import tushare_read_lock, tushare_write_lock
    
    if str(path).endswith('tushare.db'):
        if read_only:
            lock_ctx = tushare_read_lock(timeout=10)
        else:
            lock_ctx = tushare_write_lock(timeout=30)
    else:
        class NoLock:
            def __enter__(self): pass
            def __exit__(self, *args): pass
        lock_ctx = NoLock()
    
    with lock_ctx:
        _ensure_tmp_dir()
        
        for attempt in range(retry * 2 + 1):
            try:
                con = duckdb.connect(str(path), read_only=read_only)
                _apply_stable_settings(con)
                return con
            except Exception as e:
                err = str(e)
                if attempt < retry and ('checksum' in err.lower() or 'wal' in err.lower()):
                    # WAL 损坏，清理后重试
                    _clean_wal(path)
                    time.sleep(0.5)
                    continue
                # 最终 fallback
                if 'checksum' in err.lower():
                    _clean_wal(path)
                    time.sleep(0.5)
                    continue
                raise


def get_tushare_db(read_only=True):
    """获取主力数据库连接 (tushare.db) — 带防损坏保护

    Args:
        read_only: 默认 True. 除 API 自动更新脚本外，所有组件必须使用只读模式.
    """
    from .db_lock import tushare_read_lock, tushare_write_lock
    
    if read_only:
        lock_ctx = tushare_read_lock(timeout=10)
    else:
        lock_ctx = tushare_write_lock(timeout=30)
    
    with lock_ctx:
        return _safe_connect(TUSHARE_DB_PATH, read_only, retry=1)


def get_tushare_db_write():
    """获取可写连接 (仅限 API 自动更新脚本使用)"""
    from .db_lock import tushare_write_lock
    
    with tushare_write_lock(timeout=60):
        _ensure_tmp_dir()
        
        con = duckdb.connect(str(TUSHARE_DB_PATH), read_only=False)
        _apply_stable_settings(con)
        
        try:
            con.execute("SET wal_autocheckpoint = 100")
        except Exception:
            pass
        
        return con


def checkpoint(db):
    """执行 CHECKPOINT 并关闭,确保数据落盘"""
    try:
        db.execute("CHECKPOINT")
    except Exception:
        pass
    db.close()


# --- 状态数据库 (SQLite) ---
# v2 三层存储（2026-08-29）：ledger.db=热层账本, signals.db=温层信号
# state.db 已冻结为 state.db.pre_split（T5 后只读），新代码一律走下面三个入口
LEDGER_DB_PATH = BASE / 'ledger.db'
SIGNALS_DB_PATH = BASE / 'signals.db'
FACTORS_DB_PATH = BASE / 'factors.db'

def _sqlite_connect(path, read_only=False):
    """统一 SQLite 参数：P7 禁静默新建 + busy_timeout 兜底"""
    import sqlite3
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"P7: {p.name} 不存在，禁止静默新建空库。检查连接入口。")
    uri = f"file:{p}?mode=ro" if read_only else str(p)
    conn = sqlite3.connect(uri, uri=read_only, timeout=30)
    if not read_only:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    if not read_only:
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def connect_ledger(read_only=False):
    """热层：holdings/trade_log/account_balance/strategy_*/watchlist/position_peaks 等"""
    return _sqlite_connect(LEDGER_DB_PATH, read_only)

def connect_signals(read_only=False):
    """温层：signal_history/fusion_3f_*/new_factors/flow_alpha/vol_adj/*_ic*/tdx_* 等"""
    return _sqlite_connect(SIGNALS_DB_PATH, read_only)

def connect_factors(read_only=False):
    """冷层：因子历史归档表（9/12 起 archive_monthly.sh 按月 APPEND）"""
    return _sqlite_connect(FACTORS_DB_PATH, read_only)

def connect_all(read_only=False):
    """三层统一视图：main=ledger 本体, sig.=signals, fac.=factors。
    跨冷温层查询/归档对账用。"""
    conn = _sqlite_connect(LEDGER_DB_PATH, read_only)
    conn.execute("ATTACH DATABASE ? AS sig", (str(SIGNALS_DB_PATH),))
    conn.execute("ATTACH DATABASE ? AS fac", (str(FACTORS_DB_PATH),))
    return conn

def connect_state(read_only=False):
    """跨层查询统一入口：main=ledger 本体，信号表带 sig. 前缀（ATTACH signals）。
    例: SELECT ... FROM holdings h JOIN sig.fusion_3f_signals s ON ..."""
    conn = _sqlite_connect(LEDGER_DB_PATH, read_only)
    conn.execute("ATTACH DATABASE ? AS sig", (str(SIGNALS_DB_PATH),))
    return conn

def get_state_db():
    """[v2 兼容入口] 跨层查询连接：main=ledger.db 本体，ATTACH signals.db AS sig。
    非限定表名自动解析（SQLite 按 ATTACH 顺序查找），存量查询体零改动。
    新代码请直接用 connect_ledger / connect_signals。"""
    conn = _sqlite_connect(LEDGER_DB_PATH, read_only=False)
    conn.execute("ATTACH DATABASE ? AS sig", (str(SIGNALS_DB_PATH),))
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# --- 向后兼容别名 ---
def get_stock_db(read_only=True):
    """获取主力数据库连接(tushare.db)"""
    # 旧代码调用 get_stock_db() 时,自动重定向到 tushare.db
    return get_tushare_db(read_only)


def get_db(read_only=True):
    """通用入口 -> tushare.db"""
    return get_tushare_db(read_only)


def get_db_path():
    """返回当前主力库路径"""
    return str(TUSHARE_DB_PATH)
