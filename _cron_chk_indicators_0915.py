import duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = duckdb.connect('indicators.db', read_only=True)
tabs = [r[0] for r in c.execute("SHOW TABLES").fetchall()]
print("tables:", tabs)
for t in tabs:
    try:
        n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        cols = [d[0] for d in c.execute("SELECT * FROM %s LIMIT 0" % t).description]
        dc = 'trade_date' if 'trade_date' in cols else ('date' if 'date' in cols else None)
        if dc:
            mx = c.execute("SELECT MAX(%s) FROM %s" % (dc, t)).fetchone()[0]
            last5 = c.execute("SELECT %s, COUNT(*) FROM %s GROUP BY 1 ORDER BY 1 DESC LIMIT 5" % (dc, t)).fetchall()
        else:
            mx, last5 = None, None
        print("%s: rows=%d cols=%d max=%s" % (t, n, len(cols), mx))
        print("   last5:", last5)
        print("   colnames:", cols[:25])
    except Exception as e:
        print(t, "ERR", e)
