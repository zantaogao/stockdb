#!/usr/bin/env python3
"""Retrain-need check part 3: factor_ic_roll + etf_scores."""
import sqlite3
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
con = sqlite3.connect(str(BASE / 'state.db'))
con.row_factory = sqlite3.Row

# factor_ic_roll schema
cur = con.execute("PRAGMA table_info(factor_ic_roll)")
cols = [r[1] for r in cur.fetchall()]
print("factor_ic_roll cols:", cols)
print()

# distinct factor names + windows
cur = con.execute("SELECT DISTINCT factor_name, window FROM factor_ic_roll ORDER BY factor_name, window")
print("factors:", cur.fetchall())
print()

# latest rows per factor/window
try:
    cur = con.execute("""
        SELECT * FROM factor_ic_roll
        ORDER BY as_of_date DESC LIMIT 30""")
    rows = cur.fetchall()
    print(f"--- factor_ic_roll 最新 30 行 (共 {con.execute('SELECT COUNT(*) FROM factor_ic_roll').fetchone()[0]} 行) ---")
    for r in rows:
        d = dict(r)
        print("  ", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()})
except Exception as e:
    print("err:", e)
print()

# aggregation: for each factor+window, latest rolling IC & recent trend
print("--- 各 factor/window 最近均值（最新5条 vs 全部均值） ---")
try:
    cur = con.execute("SELECT DISTINCT factor_name, window FROM factor_ic_roll")
    for fname, win in cur.fetchall():
        rows = con.execute("""
            SELECT mean_ic FROM factor_ic_roll
            WHERE factor_name=? AND window=? ORDER BY as_of_date DESC LIMIT 5""", (fname, win)).fetchall()
        allrows = con.execute("""
            SELECT mean_ic FROM factor_ic_roll
            WHERE factor_name=? AND window=?""", (fname, win)).fetchall()
        def avg(rs):
            vals = [r[0] for r in rs if r[0] is not None]
            return sum(vals)/len(vals) if vals else None
        print(f"  {fname} (win={win}): 近5条均值={avg(rows) and round(avg(rows),4)}  全部({len(allrows)}条)均值={avg(allrows) and round(avg(allrows),4)}")
except Exception as e:
    print("agg err:", e)
print()

# etf_scores: ETF model IC
cur = con.execute("PRAGMA table_info(etf_scores)")
print("etf_scores cols:", [r[1] for r in cur.fetchall()])
try:
    cur = con.execute("SELECT * FROM etf_scores ORDER BY scan_date DESC LIMIT 8")
    rows = cur.fetchall()
    print("--- etf_scores 最新 8 行 ---")
    for r in rows:
        print("  ", tuple(r))
except Exception as e:
    print("etf err:", e)

con.close()
