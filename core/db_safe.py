#!/usr/bin/env python3
"""
安全数据库操作模块
================
特点：
1. WAL 模式 + 自动 checkpoint
2. 原子读写（临时文件 + rename）
3. 自动备份（每次写前备份）
4. 异常恢复（损坏时自动修复）
"""
from __future__ import annotations

import duckdb
import json
import shutil
import tempfile
import os
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Generator

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'ledger.db'  # v2热层（state.db 已冻结，本模块无活跃调用方，仅备用）
BACKUP_DIR = BASE / 'db_backups'


def ensure_backup_dir():
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def backup_db(db_path: Optional[Path] = None) -> Optional[Path]:
    """
    原子备份数据库
    返回备份文件路径，失败返回 None
    """
    db_path = db_path or DB_PATH
    if not db_path.exists():
        return None
    
    ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = BACKUP_DIR / f'state_{timestamp}.db'
    temp_path = BACKUP_DIR / f'state_{timestamp}.db.tmp'
    
    try:
        # 先写临时文件
        shutil.copy2(db_path, temp_path)
        # 成功后再重命名
        temp_path.rename(backup_path)
        
        # 清理旧备份（保留最近 7 天）
        cleanup_old_backups(days=7)
        
        return backup_path
    except Exception as e:
        # 失败时删除临时文件
        if temp_path.exists():
            temp_path.unlink()
        print(f"⚠️ 备份失败：{e}")
        return None


def cleanup_old_backups(days: int = 7):
    """清理超过指定天数的备份"""
    if not BACKUP_DIR.exists():
        return
    
    cutoff = datetime.now().timestamp() - (days * 86400)
    for f in BACKUP_DIR.glob('state_*.db'):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except:
                pass


@contextmanager
def get_db_connection(db_path: Optional[Path] = None) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """
    安全获取数据库连接
    自动设置 WAL 模式和 checkpoint
    """
    db_path = db_path or DB_PATH
    
    # 检查数据库是否损坏
    if not check_db_integrity(db_path):
        print(f"⚠️ 数据库损坏，尝试从备份恢复...")
        if not restore_from_backup(db_path):
            raise RuntimeError(f"数据库损坏且无可用备份：{db_path}")
    
    conn = duckdb.connect(str(db_path))
    
    # 设置 WAL 模式（如果还没设置）
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=1000")  # 每 1000 页自动 checkpoint
    except:
        pass
    
    try:
        yield conn
    finally:
        # 关闭前强制 checkpoint
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except:
            pass
        conn.close()


def check_db_integrity(db_path: Optional[Path] = None) -> bool:
    """检查数据库完整性（直接连接，避免递归）"""
    db_path = db_path or DB_PATH
    if not db_path.exists():
        return False
    
    try:
        # 直接连接，不用 context manager 避免递归
        conn = duckdb.connect(str(db_path))
        # 尝试执行简单查询
        conn.execute("SELECT 1")
        # 检查关键表是否存在
        tables = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'").fetchone()[0]
        conn.close()
        return tables > 0
    except:
        return False


def restore_from_backup(db_path: Optional[Path] = None) -> bool:
    """
    从最新备份恢复数据库
    返回是否成功
    """
    db_path = db_path or DB_PATH
    ensure_backup_dir()
    
    # 找最新的备份
    backups = sorted(BACKUP_DIR.glob('state_*.db'), key=lambda f: f.stat().st_mtime, reverse=True)
    if not backups:
        return False
    
    latest_backup = backups[0]
    
    try:
        # 先备份当前损坏的文件
        damaged_backup = BACKUP_DIR / f'damaged_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        shutil.copy2(db_path, damaged_backup)
        
        # 恢复
        shutil.copy2(latest_backup, db_path)
        print(f"✅ 已从 {latest_backup.name} 恢复")
        return True
    except Exception as e:
        print(f"❌ 恢复失败：{e}")
        return False


def atomic_write_db(source_path: Path, target_path: Optional[Path] = None):
    """
    原子写入数据库（先写临时文件，成功后再替换）
    用于从内存/其他源写入整个数据库
    """
    target_path = target_path or DB_PATH
    temp_path = target_path.with_suffix('.db.tmp')
    
    try:
        shutil.copy2(source_path, temp_path)
        temp_path.rename(target_path)
        
        # 触发备份
        backup_db(target_path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise e


# ── 查询辅助函数 ────────────────────────────────────────

def query_holdings(account_id: Optional[str] = None) -> list:
    """查询持仓（单账户 main，account_id 参数保留兼容）"""
    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT code, name, shares, avg_cost, latest_price, buy_date, status
            FROM holdings 
            WHERE status = 'hold'
            ORDER BY code
        """).fetchall()
        
        return [
            {
                'code': r[0], 'name': r[1], 'shares': r[2],
                'avg_cost': r[3], 'latest_price': r[4],
                'buy_date': r[5], 'status': r[6],
                'account_id': 'main'  # 固定为 main 账户
            }
            for r in result
        ]


def query_account_balance(account_id: str = 'main') -> Optional[dict]:
    """查询账户资金"""
    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT account_id, account_name, initial_capital, cash_balance, total_value, last_update
            FROM account_balance 
            WHERE account_id = ?
        """, [account_id]).fetchone()
        
        if result:
            return {
                'account_id': result[0],
                'account_name': result[1],
                'initial_capital': result[2],
                'cash_balance': result[3],
                'total_value': result[4],
                'last_update': str(result[5])
            }
        return None


def query_trade_logs(account_id: Optional[str] = None, limit: int = 50) -> list:
    """查询交易记录"""
    with get_db_connection() as conn:
        if account_id:
            result = conn.execute("""
                SELECT id, code, name, direction, price, quantity, amount, trade_date, trade_time, strategy, signal_score, notes
                FROM trade_log
                WHERE notes NOT LIKE '%reset%'  -- 可选：排除重置记录
                ORDER BY id DESC
                LIMIT ?
            """, [limit]).fetchall()
        else:
            result = conn.execute("""
                SELECT id, code, name, direction, price, quantity, amount, trade_date, trade_time, strategy, signal_score, notes
                FROM trade_log
                ORDER BY id DESC
                LIMIT ?
            """, [limit]).fetchall()
        
        return [
            {
                'id': r[0], 'code': r[1], 'name': r[2], 'direction': r[3],
                'price': r[4], 'quantity': r[5], 'amount': r[6],
                'trade_date': r[7], 'trade_time': r[8],
                'strategy': r[9], 'signal_score': r[10], 'notes': r[11]
            }
            for r in result
        ]


def query_signals(limit: int = 10) -> list:
    """查询最新交易信号"""
    with get_db_connection() as conn:
        latest_date = conn.execute("SELECT MAX(date) FROM signal_history").fetchone()[0]
        
        result = conn.execute("""
            SELECT stock_code, stock_name, industry, reg10_pred, reg20, reg40, final_score
            FROM signal_history
            WHERE date = ?
            ORDER BY final_score DESC, reg40 DESC
            LIMIT ?
        """, [latest_date, limit]).fetchall()
        
        return [
            {
                'stock_code': r[0], 'stock_name': r[1], 'industry': r[2],
                'reg10': r[3], 'reg20': r[4], 'reg40': r[5], 'score': r[6]
            }
            for r in result
        ]


def query_ic_data(days: int = 5) -> list:
    """查询 IC 数据"""
    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT date, factor_name, rank_ic, p_value, n_stocks, ret_horizon
            FROM factor_ic_daily
            ORDER BY date DESC
            LIMIT ?
        """, [days]).fetchall()
        
        return [
            {
                'date': r[0], 'factor_name': r[1], 'rank_ic': r[2],
                'p_value': r[3], 'n_stocks': r[4], 'ret_horizon': r[5]
            }
            for r in result
        ]
