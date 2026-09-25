# 测试2: 本机tushare.db里已有的外盘数据 + news接口权限 + akshare国内源
import json, time, sqlite3
import tushare as ts

cfg = json.load(open('/Users/zantao/.hermes/stockdb/config.json'))
ts.set_token(cfg['tushare_token'])
pro = ts.pro_api()

def t(name, fn):
    try:
        s = time.time(); df = fn()
        print(f"{name} OK {len(df)}rows {time.time()-s:.1f}s")
        print(df.head(3).to_string()[:350])
    except Exception as e:
        print(f"{name} FAIL {str(e)[:130]}")
    print('---')

# 1. tushare外盘指数
for c in ['IXIC','DJIA','SPX','HSTECH','HSI','N225']:
    t(f'index_global {c}', lambda c=c: pro.index_global(ts_code=c, start_date='20260828', end_date='20260902'))

# 2. news 快讯接口权限
t('news sina', lambda: pro.news(src='sina', start_date='2026-09-02 08:00:00', end_date='2026-09-02 09:00:00', count=5))

# 3. COMEX铜/金、美元指数类
t('fx_ob_list(外汇)', lambda: pro.fx_ob_list(exch='FX-BD'))
t('hk_daily 港股', lambda: pro.hk_daily(trade_date='20260902'))