"""临时核查：今日(20260908)全市场除权 ∩ 持仓。只读，不改任何东西。"""
import warnings; warnings.filterwarnings('ignore')
import sys, sqlite3, re, os
BASE = os.path.expanduser('~/.hermes/stockdb')
sys.path.insert(0, BASE)

tok = None
for f in [os.path.join(BASE, 'config.json')]:
    if os.path.exists(f):
        m = re.search(r'"tushare_token"\s*:\s*"([^"]+)"', open(f).read())
        if m:
            tok = m.group(1)
print('token found:', bool(tok))

import tushare as ts
ts.set_token(tok)
pro = ts.pro_api()
df = pro.dividend(ex_date='20260908')
n = 0 if df is None else len(df)
print('今日除权API行数:', n)
if n:
    led = sqlite3.connect(os.path.join(BASE, 'ledger.db'), timeout=5)
    hold = {r[0] for r in led.execute("SELECT code FROM holdings WHERE status='hold'").fetchall()}
    for _, r in df.iterrows():
        code = str(r['ts_code']).split('.')[0]
        if code in hold:
            print('命中持仓:', r['ts_code'], 'stk_bo=', r.get('stk_bo'),
                  'stk_trans=', r.get('stk_trans'), 'cash_div=', r.get('cash_div'),
                  'div_proc=', r.get('div_proc'))
    print('（无命中输出=持仓今日无除权）')