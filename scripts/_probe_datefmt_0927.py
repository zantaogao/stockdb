# 逐票重算ex列时各代码路径的日期格式实查(免再猜格式)
import sys, duckdb
sys.path.insert(0,'/Users/zantao/.hermes/stockdb'); sys.path.insert(0,'/Users/zantao/.hermes/stockdb/scripts')
from feat_tushare import load_index_data, get_board_index
con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for ts in ['000001.SZ','300581.SZ']:
    r=con.execute(f"SELECT trade_date FROM daily WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 1").fetchone()
    a=con.execute(f"SELECT trade_date FROM adj_factor WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 1").fetchone()
    print(ts, 'daily:', repr(r[0]), 'adj:', repr(a[0]))
idx=load_index_data()
b=idx.get(get_board_index('000001'))
print('idx键样例:', repr(b['dates'][-1]))
