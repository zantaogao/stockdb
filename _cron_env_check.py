import sys
print('python:', sys.executable, sys.version.split()[0])
try:
    import duckdb
    print('duckdb OK', duckdb.__version__)
except Exception as e:
    print('duckdb FAIL:', e)
try:
    import tushare
    print('tushare OK', tushare.__version__)
except Exception as e:
    print('tushare FAIL:', e)
