import json, glob, os, sqlite3
base = os.path.expanduser('~/.hermes/stockdb')
import duckdb
con = duckdb.connect(f'{base}/tushare.db', read_only=True)
rows = con.execute("SELECT industry, COUNT(*) FROM stock_basic GROUP BY industry ORDER BY COUNT(*) DESC").fetchall()
zzz = [r for r in rows if 'ZZZ' in (r[0] or '')]
print('industries total:', len(rows))
print('ZZZ industries:', zzz)
print('top5:', rows[:5])
con.close()
for p in glob.glob(f'{base}/pending.json') + glob.glob(f'{base}/**/pending.json', recursive=True):
    try:
        d = json.load(open(p))
        print('pending:', p, d if d else 'EMPTY')
    except Exception as e:
        print('pending:', p, 'ERR', e)