# Cross-verify: re-aggregate 0917/0921 from min1_archive via agg_day, compare vs tdx_intraday_feat
import duckdb, sqlite3, importlib.util, pandas as pd
BASE='/Users/zantao/.hermes/stockdb'
spec = importlib.util.spec_from_file_location('tdxagg', f'{BASE}/scripts/tdx_intraday_agg.py')
tdxagg = importlib.util.module_from_spec(spec); spec.loader.exec_module(tdxagg)
arch = duckdb.connect(f'{BASE}/tdx_archive.db', read_only=True)
sig = sqlite3.connect(f'file:{BASE}/signals.db?mode=ro', uri=True)

for d in (20260917, 20260921):
    df = arch.execute(f'''select cast(code as varchar) as code, tm, open, "high", "low",
                          "close" as cl, volume as vol from min1_archive where date={d}''').df()
    df = df.rename(columns={'cl':'close'})
    rows=[]
    for c,g in df.groupby('code', sort=False):
        g=g.sort_values('tm').reset_index(drop=True)
        g['date']=d
        r=tdxagg.agg_day(g[['date','tm','open','high','low','close','vol']])
        if r: rows.append({**r,'code':c})
    calc=pd.DataFrame(rows)
    db=pd.read_sql('select * from tdx_intraday_feat where date=?', sig, params=[d])
    m=calc.merge(db, on='code', suffixes=('_c','_d'))
    print(d,'calc=%d db=%d matched=%d'%(len(calc),len(db),len(m)))
    for col in ['open30_ret','tail30_ret','tail5_ret','vwap_dev','rv_1m','amp_intra','vol_dist_am','vol_dist_tail','last_vol_share','n_bars']:
        print('  ',col,'maxdiff=%.2e'%(m[col+'_c'].astype(float)-m[col+'_d'].astype(float)).abs().max())
