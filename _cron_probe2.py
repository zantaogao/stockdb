import sys
print('EXE:', sys.executable, sys.version.split()[0])
import duckdb, numpy, tushare, pandas
print('duckdb', duckdb.__version__, '| numpy', numpy.__version__, '| tushare', tushare.__version__, '| pandas', pandas.__version__)
try:
    import lightgbm; print('lightgbm', lightgbm.__version__)
except Exception as e:
    print('lightgbm FAIL:', repr(e))
try:
    import core.scoring; print('core.scoring OK')
except Exception as e:
    print('core.scoring FAIL:', repr(e))
