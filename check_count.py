import duckdb
c = duckdb.connect('state.db')
print('signal_history 记录数:', c.execute('SELECT COUNT(*) FROM signal_history').fetchone()[0])
