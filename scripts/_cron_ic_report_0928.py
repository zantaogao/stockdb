import sqlite3
db = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
cur = db.cursor()
print('## ic_daily (模型IC, 最新6个calc_date)')
for r in cur.execute("SELECT calc_date,signal_date,sample_size,ic_reg10,ic_reg20,ic_reg40,ic_fusion FROM ic_daily ORDER BY calc_date DESC LIMIT 6"):
    print(r)
print('## fusion_ic_daily (单日)')
for r in cur.execute("SELECT date,ic,samples,win_rate FROM fusion_ic_daily ORDER BY date DESC LIMIT 5"):
    print(r)
print('## cmmr_ic_daily')
for r in cur.execute("SELECT date,ic,samples,win_rate FROM cmmr_ic_daily ORDER BY date DESC LIMIT 5"):
    print(r)
print('## center_dual_ic_daily')
for r in cur.execute("SELECT date,ic,samples FROM center_dual_ic_daily ORDER BY date DESC LIMIT 5"):
    print(r)
print('## etf_ic')
for r in cur.execute("SELECT calc_date,signal_date,ic_etf,ic_spearman,ic_20d FROM etf_ic ORDER BY calc_date DESC LIMIT 3"):
    print(r)
try:
    print('## ic_window cols')
    print([c[1] for c in cur.execute("PRAGMA table_info(ic_window)")])
    for r in cur.execute("SELECT * FROM ic_window ORDER BY 1 DESC LIMIT 6"):
        print(r)
except Exception as e:
    print('ic_window ERR', e)
