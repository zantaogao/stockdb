import duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
con = duckdb.connect()
con.execute("ATTACH 'signals.db' AS sig (READ_ONLY)")
print('=== tdx_intraday_feat date coverage (last 8) ===')
for r in con.execute("SELECT date, COUNT(*), SUM(CASE WHEN open30_ret<0 AND vwap_dev>0 AND amp_intra>0.05 THEN 1 ELSE 0 END) AS dup, SUM(CASE WHEN tail30_ret>0.015 AND vwap_dev>0 THEN 1 ELSE 0 END) AS tail30, SUM(CASE WHEN tail5_ret>0.015 THEN 1 ELSE 0 END) AS tail5 FROM sig.tdx_intraday_feat GROUP BY date ORDER BY date DESC LIMIT 8").fetchall():
    print(r, 'dup_frac=%.3f' % (r[2]/r[1]))
print('\n=== columns ===')
print([c[0] for c in con.execute("DESCRIBE sig.tdx_intraday_feat").fetchall()])
print('\n=== 20260911 sample stats ===')
for r in con.execute("SELECT COUNT(*), AVG(open30_ret), AVG(vwap_dev), AVG(amp_intra), SUM(CASE WHEN open30_ret IS NULL THEN 1 ELSE 0 END) FROM sig.tdx_intraday_feat WHERE date='20260911'").fetchall():
    print(r)
