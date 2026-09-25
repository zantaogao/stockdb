# -*- coding: utf-8 -*-
# IC 序列 + universe.json 每股口径指标 + 板块10日
import duckdb, sqlite3, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
sc = sqlite3.connect('signals.db')

def dump(t, datecol, iccols):
    cols = ', '.join(iccols)
    rows = sc.execute(f"SELECT {datecol}, {cols} FROM {t} ORDER BY {datecol} DESC LIMIT 12").fetchall()
    print('=====', t, '=====')
    for r in reversed(rows):
        print(r[0], ' | '.join('%s=%s' % (c, ('%.4f' % float(v) if v is not None else 'NA')) for c, v in zip(iccols, r[1:])))

dump('ic_daily', 'signal_date', ['ic_reg10','ic_reg20','ic_reg40','ic_fusion'])
dump('fusion_ic_daily', 'signal_date', ['ic'])
dump('center_dual_ic_daily', 'signal_date', ['ic_center','ic_reg','ic_dual'])
dump('cmmr_ic_daily', 'signal_date', ['ic'])
print('===== ic_window 结构 =====')
print([r[1] for r in sc.execute('PRAGMA table_info(ic_window)').fetchall()])
rows = sc.execute("SELECT * FROM ic_window ORDER BY signal_date DESC LIMIT 14").fetchall()
for r in reversed(rows): print(r)

print('===== universe.json 每股指标（60票样本） =====')
uni = json.load(open('analysis/opinion_universe.json'))
u = uni['universe']
if isinstance(u, dict):
    k0 = list(u.keys())[0]
    print('sample keys:', k0, u[k0])
elif isinstance(u, list):
    print('sample:', u[0])
for bn, lst in uni['top10'].items():
    print(bn, json.dumps(lst[:2], ensure_ascii=False))
