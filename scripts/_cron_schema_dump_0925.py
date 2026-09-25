# 导出关键表 DDL 入 schema/（Task 1.2 schema 版本化基线 2026-09-25；此后表结构变更须同步改本目录并 git 提交）
import sqlite3, duckdb, pathlib
from pathlib import Path
OUT = Path('/Users/zantao/.hermes/stockdb/schema'); OUT.mkdir(exist_ok=True)

def dump_sqlite(db, tables, name):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    import datetime as _dt
    lines = [f'-- {db} 关键表 DDL（{_dt.date.today()} 基线）']
    for t in tables:
        row = con.execute("select sql from sqlite_master where type='table' and name=?", (t,)).fetchone()
        if row and row[0]: lines.append(row[0].rstrip()+';')
        else: lines.append(f'-- [缺] {t}')
    (OUT/name).write_text('\n'.join(lines)+'\n')
    print(name, len(lines)-1, '表')

dump_sqlite('/Users/zantao/.hermes/stockdb/ledger.db',
    ['daily_nav','trade_log','strategy_accounts','defense_state','account_balance'], 'ledger.sql')

# ledger 全部表名兜底
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
print('ledger 全部表:', [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")])
