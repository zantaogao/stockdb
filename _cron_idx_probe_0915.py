import os, sys
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
import tushare as ts
tok = None
for p in ['~/.tushare_token', '~/.hermes/stockdb/.tushare_token', '~/.hermes/tushare_token']:
    fp = os.path.expanduser(p)
    if os.path.exists(fp):
        tok = open(fp).read().strip(); print('token from', fp); break
if not tok:
    tok = os.environ.get('TUSHARE_TOKEN')
if not tok:
    # try DB config table
    import duckdb
    try:
        c = duckdb.connect('tushare.db', read_only=True)
        print('config tables:', [r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%config%' OR table_name LIKE '%token%'").fetchall()])
    except Exception as e:
        print('db conf err', e)
if tok:
    pro = ts.pro_api(tok)
    for code, rng in [('000001.SH', '20260915'), ('000852.SH', '20260915')]:
        try:
            df = pro.index_daily(ts_code=code, start_date=rng, end_date=rng)
            print(code, rng, 'rows=', 0 if df is None else len(df), (df.to_dict('records')[:1] if df is not None and len(df) else ''))
        except Exception as e:
            print(code, 'ERR', str(e)[:120])
