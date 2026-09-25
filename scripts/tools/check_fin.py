"""Quick check: fin_income columns"""
import duckdb
con = duckdb.connect(r"C:\Users\pumma\factor_lib\stock.db", read_only=True)
cols = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='fin_income'").fetchdf()
print(cols)
