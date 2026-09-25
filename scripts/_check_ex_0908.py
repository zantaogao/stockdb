import json, sqlite3, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import tushare as ts
cfg = json.load(open('/Users/zantao/.hermes/stockdb/config.json'))
ts.set_token(cfg['tushare_token'])
pro = ts.pro_api()
df = pro.dividend(ex_date='20260908')
print('today ex-date rows:', 0 if df is None else len(df))
if df is not None and len(df):
    print(df[['ts_code','ex_date','stk_div','stk_bo_rate','stk_trans_rate','cash_div']].to_string())
    codes = {str(c).split('.')[0] for c in df['ts_code']}
    c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
    hold = {r[0] for r in c.execute('SELECT code FROM holdings').fetchall()}
    print('命中主账户持仓:', sorted(codes & hold))
    from pathlib import Path
    for f in Path('/Users/zantao/.hermes/stockdb/sim_accounts').glob('*.json'):
        if f.stem == 'main': continue
        try: d = json.load(open(f))
        except Exception: continue
        pos = {p.get('code') for p in d.get('positions', []) if isinstance(p, dict)}
        hit = {x for x in pos if x in codes}
        if hit: print(f'命中 {f.stem}:', hit)