#!/usr/bin/env python3
"""
创建 CMMR IC 表结构
"""
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent.parent
STATE_DB = BASE / 'signals.db'  # v2温层

def create_tables():
    conn = sqlite3.connect(str(STATE_DB))
    
    # 创建 CMMR 独立策略 IC 表
    conn.execute("""CREATE TABLE IF NOT EXISTS cmmr_ic_daily (
        date DATE PRIMARY KEY,
        ic DOUBLE,
        samples INTEGER,
        positive_days INTEGER,
        win_rate DOUBLE
    )""")
    print("✅ cmmr_ic_daily 表已创建")
    
    # 创建 CMMR+ 模型融合 IC 表（原名"三因子融合"系误称，2026-08-10 更正）
    conn.execute("""CREATE TABLE IF NOT EXISTS fusion_ic_daily (
        date DATE PRIMARY KEY,
        ic DOUBLE,
        samples INTEGER,
        positive_days INTEGER,
        win_rate DOUBLE
    )""")
    print("✅ fusion_ic_daily 表已创建")
    
    conn.commit()
    conn.close()
    print("✅ 所有 CMMR 表创建完成")

if __name__ == '__main__':
    create_tables()
