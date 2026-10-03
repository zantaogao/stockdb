import sqlite3, json

for path in ['/Users/zantao/.hermes/stockdb/ledger.db', '/Users/zantao/.hermes/stockdb/data/ledger.db']:
    try:
        con = sqlite3.connect('file:' + path + '?mode=ro', uri=True)
        print('=== ' + path)
        print('cols:', [c[1] for c in con.execute('pragma table_info(ca_run_log)')])
        print('last 5:', con.execute("select * from ca_run_log order by run_date desc limit 5").fetchall())
    except Exception as e:
        print(path, 'ERR', e)
        continue
    # any CA events for held stocks today?
    try:
        rows = con.execute("select * from ca_adjustments order by rowid desc limit 5").fetchall()
        print('ca_adjustments last5:', rows)
    except Exception as e:
        print('ca_adjustments ERR', e)
    con.close()

# trading calendar: is 20261001 a trading day?
d = json.load(open('/Users/zantao/.hermes/stockdb/data/trade_cal.json'))
opens = set(d['is_open_dates'])
for dt in ['20260928','20260929','20260930','20261001','20261002','20261008','20261009']:
    print(dt, 'open' if dt in opens else 'CLOSED')
