#!/bin/bash
# 找 daily/trade_cal 表所在库
for db in "$HOME"/.hermes/stockdb/data/*.db "$HOME"/.hermes/stockdb/data/*.duckdb; do
  [ -f "$db" ] || continue
  /usr/bin/python3 -B - "$db" <<'PYEOF' 2>/dev/null
import duckdb, sys, os
path = sys.argv[1]
try:
    c = duckdb.connect(path, read_only=True)
    ts = [t[0] for t in c.execute("select table_name from information_schema.tables where table_name in ('daily','trade_cal','stock_daily')").fetchall()]
    if ts:
        print(os.path.basename(path), ts)
        for t in ts:
            try:
                mx = c.execute(f"select max(trade_date) from {t}").fetchone() if t!='trade_cal' else None
                if t == 'trade_cal':
                    rows = c.execute("select cal_date,is_open from trade_cal where cal_date between '20260928' and '20261012' order by 1").fetchall()
                    print("   trade_cal 9/28-10/12:", rows)
                elif mx:
                    print(f"   {t} 最新:", mx)
            except Exception as e:
                print("   q err", t, str(e)[:50])
except Exception as e:
    pass
PYEOF
done
