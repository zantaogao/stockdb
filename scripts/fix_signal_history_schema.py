#!/usr/bin/env python3
"""
修复 signal_history 表结构，添加 CMMR 相关列
"""
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent.parent
STATE_DB = BASE / 'state.db'

def fix_schema():
    conn = sqlite3.connect(str(STATE_DB))
    
    # 检查当前表结构
    cursor = conn.execute("PRAGMA table_info(signal_history)")
    columns = {row[1] for row in cursor.fetchall()}
    print(f"当前列：{columns}")
    
    # 需要添加的列
    new_cols = ['old_score', 'cmmr_score', 'fusion_score_cmmr', 'ma40_slope']
    
    for col in new_cols:
        if col in columns:
            print(f"✅ {col} 已存在")
        else:
            try:
                conn.execute(f"ALTER TABLE signal_history ADD COLUMN {col} DOUBLE")
                print(f"✅ 已添加 {col} 列")
            except Exception as e:
                print(f"❌ 添加 {col} 失败：{e}")
    
    conn.commit()
    conn.close()
    print("✅ 表结构修复完成")

if __name__ == '__main__':
    fix_schema()
