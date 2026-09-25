import duckdb
c = duckdb.connect('state.db')
cols = c.execute('PRAGMA table_info(fin_income);').fetchall()
print("fin_income columns:")
for col in cols:
    print(f"  {col[1]}")
