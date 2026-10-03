#!/usr/bin/env python3
"""复现 tdx_archive.py 的 INSERT 路径，确认 20260929 归档失败的根因（只写临时库，不碰真库）"""
import duckdb, pandas as pd, os, tempfile

DB = os.path.join(tempfile.gettempdir(), '_probe_dup_0929.duckdb')
if os.path.exists(DB): os.remove(DB)
df = pd.read_csv('/tmp/tdx_min1_recent.csv', dtype={'code': str})
df['date'] = df['datetime'].str[:8].astype(int)
df['tm'] = df['datetime'].str[9:11].astype(int) * 60 + df['datetime'].str[11:13].astype(int)
df = df[['date', 'code', 'market', 'tm', 'open', 'high', 'low', 'close', 'volume']]
dupmask = df.duplicated(subset=['date','code','market','tm'], keep=False)
print(f'CSV 总行数={len(df)} 违反主键的重复行={dupmask.sum()}')
print(df[dupmask].sort_values(['date','code','tm']).head(8).to_string())
db = duckdb.connect(DB)
db.execute("""CREATE TABLE IF NOT EXISTS min1_archive (
    date INTEGER, code VARCHAR, market VARCHAR, tm INTEGER,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
    PRIMARY KEY (date, code, market, tm))""")
try:
    db.execute("INSERT INTO min1_archive SELECT date, code, market, tm, open, high, low, close, volume FROM df")
    print('INSERT 成功（说明重复键不是根因）')
except Exception as e:
    print(f'INSERT 失败: {type(e).__name__}: {str(e)[:300]}')
db.close(); os.remove(DB)
