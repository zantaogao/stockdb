# Probe: why does agg_day return None for codes in the 0917 5min export?
import pandas as pd, importlib.util
BASE='/Users/zantao/.hermes/stockdb'
spec = importlib.util.spec_from_file_location('tdxagg', f'{BASE}/scripts/tdx_intraday_agg.py')
tdxagg = importlib.util.module_from_spec(spec); spec.loader.exec_module(tdxagg)
df = pd.read_csv('/tmp/_rev_min5_20260917.csv', dtype={'code':str})
df=df.rename(columns={'volume':'vol'}); df['date']=20260917
codes = df['code'].nunique()
n_ok=0; n_none=0; none_codes=[]
for code,grp in df.groupby('code',sort=False):
    g=grp.sort_values('tm').reset_index(drop=True)
    r=tdxagg.agg_day(g)
    if r: n_ok+=1
    else:
        n_none+=1
        if len(none_codes)<5: none_codes.append((code,len(g)))
print('codes',codes,'ok',n_ok,'none',n_none, none_codes)
