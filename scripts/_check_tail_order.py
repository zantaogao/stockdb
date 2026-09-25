#!/usr/bin/env python3
"""③a 尾盘异动行序自检（2026-09-11 建：报告行序必须与哈希种子无关）

用法（跨 seed 比对，逐字节应一致）：
    for s in 0 1 2 3 7; do PYTHONHASHSEED=$s python3 -B scripts/_check_tail_order.py > /tmp/to$s.txt; done
    for s in 1 2 3 7; do diff /tmp/to0.txt /tmp/to$s.txt; done

背景：原 ③a 用集合推导收集 entrap（`{r[0] for r in ...}`），输出顺序随 PYTHONHASHSEED 漂移
（同一份数据两次运行报告行序不同）。已抽成 daily_report.tail_alerts() 并显式排序。
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'scripts'))

spec = importlib.util.spec_from_file_location('dr', str(BASE / 'scripts' / 'daily_report.py'))
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

state = sqlite3.connect(str(dr.STATE_DB), timeout=30)
led = BASE / 'ledger.db'
if led.exists():
    state.execute("ATTACH DATABASE ? AS led", (str(led),))   # MacBook v2：holdings 在 ledger.db
d3 = str(state.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0] or '')
sb = dr.get_st_names()

print(f'd3={d3} 哈希随机化={sys.flags.hash_randomization}')
for ln in dr.tail_alerts(state, sb, d3):
    print(ln)
