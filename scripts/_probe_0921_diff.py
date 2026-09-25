# Locate which codes/discrepancies: compare archive min1 rows vs CSV rows for 0921
import duckdb, pandas as pd, collections
BASE='/Users/zantao/.hermes/stockdb'
arch = duckdb.connect(f'{BASE}/tdx_archive.db', read_only=True)

csv = pd.read_csv('/tmp/tdx_min1_recent.csv', dtype={'code':str})
csv = csv[csv['datetime'].str[:8]=='20260921'].copy()
csv['tm']=csv['datetime'].str[9:11].astype(int)*60+csv['datetime'].str[11:13].astype(int)

arc = arch.execute("select cast(code as varchar) code, tm, open, \"high\", \"low\", \"close\" cl, volume vol from min1_archive where date=20260921").df()

# join on (code,tm) and compare close values
m = csv.merge(arc, on=['code','tm'], how='outer', suffixes=('_csv','_arc'), indicator=True)
print('merge:', m['_merge'].value_counts().to_dict())
both = m[m['_merge']=='both']
diff = both[(both['cl']-both['close']).abs() > 1e-6]
print('rows with different close:', len(diff))
print(diff[['code','tm','close','cl','vol_csv','vol_arc']].head(10).to_string())
print('codes affected:', diff['code'].nunique())
print('sample code tm distribution of diffs:', diff.groupby('tm').size().describe() if len(diff) else 'none')
