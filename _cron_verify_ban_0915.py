import sqlite3, os, glob, time
LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED); con.row_factory = sqlite3.Row; cur = con.cursor()
for t in ('trade_tp_ban','trade_cooldown'):
    print(f"=== {t} ===", [r[1] for r in cur.execute(f"PRAGMA table_info({t})")])
    for r in cur.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 6"):
        print(dict(r))
print("\n=== 今日 trade_log 按账户汇总 ===")
for r in cur.execute("""SELECT strategy, direction, COUNT(*) n, ROUND(SUM(amount),0) amt
                        FROM trade_log WHERE REPLACE(trade_date,'-','')='20260915' GROUP BY 1,2 ORDER BY 1,2"""):
    print(dict(r))
print("\n=== notify 推送日志 (最近) ===")
print([p for p in glob.glob(os.path.expanduser('~/.hermes/stockdb/**/notify*'), recursive=True)][:10])
print([p for p in glob.glob(os.path.expanduser('~/.hermes/stockdb/logs/*')) if 'notify' in p.lower()])
print([p for p in glob.glob(os.path.expanduser('~/.hermes/stockdb/*notify*'))])
