#!/usr/bin/env python3
"""分批运行全量选股，避免超时"""
import subprocess
import sys
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'

# 分 3 批运行
batch_size = 2000
for i in range(3):
    start = i * batch_size + 1
    end = (i + 1) * batch_size
    if i == 2:  # 最后一批包含剩余所有
        end = ""
    
    print(f"\n{'='*70}")
    print(f"批次 {i+1}/3: 股票 {start}-{end if end else '末尾'}")
    print(f"{'='*70}\n")
    
    cmd = f"cd {BASE} && python3 scripts/combined_score_v6.py --write-db --batch {start} {end}"
    result = subprocess.run(cmd, shell=True, timeout=300)
    
    if result.returncode != 0:
        print(f"⚠️ 批次 {i+1} 失败，退出码 {result.returncode}")
        if i < 2:
            ans = input("继续下一批？(y/n): ")
            if ans.lower() != 'y':
                break
    else:
        print(f"✅ 批次 {i+1} 完成")

print(f"\n{'='*70}")
print("全量选股完成")
print(f"{'='*70}")
