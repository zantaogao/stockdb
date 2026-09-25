import sys
print("python:", sys.executable, sys.version.split()[0])
import tushare, duckdb
print("tushare", tushare.__version__, "| duckdb", duckdb.__version__)
