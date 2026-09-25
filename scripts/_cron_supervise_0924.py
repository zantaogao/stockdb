# 监督tick核查：脚本本轮是否实际执行、NAV是否新鲜、是否有调仓动作
import sqlite3, os, subprocess, json

# 1. script last modified / run evidence
sh = '/Users/zantao/.hermes/scripts/strategy_accounts_daily.sh'
st = os.stat(sh)
print('script mtime:', st.st_mtime)

# 2. ledger: strategy nav table freshness
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('ledger tables:', tabs)
for t in tabs:
    try:
        cols = [c[1] for c in cur.execute(f'PRAGMA table_info({t})')]
        if 'date' in cols or 'trade_date' in cols:
            dcol = 'date' if 'date' in cols else 'trade_date'
            mx = cur.execute(f'SELECT MAX({dcol}) FROM {t}').fetchone()[0]
            n = cur.execute(f'SELECT COUNT(*) FROM {t} WHERE {dcol}=?', (mx,)).fetchone()[0]
            print(f'{t}: max_date={mx} rows_on_max={n}')
    except Exception as e:
        print(t, 'ERR', e)
con.close()

# 3. today's trades (T+1 records from script run)
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for t in tabs:
    if any(k in t.lower() for k in ('trade','order','exec','position','nav')):
        try:
            cols = [c[1] for c in cur.execute(f'PRAGMA table_info({t})')]
            print('SIG TAB', t, cols[:12])
        except Exception as e:
            print(t, 'ERR', e)
con.close()
