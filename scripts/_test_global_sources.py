# 测试无梯子下的全球资讯/外盘数据源（tushare pro + akshare 国内接口）
import json, time, sys
import tushare as ts

cfg = json.load(open('/Users/zantao/.hermes/stockdb/config.json'))
ts.set_token(cfg['tushare_token'])
pro = ts.pro_api()

def t(name, fn):
    try:
        s = time.time(); df = fn()
        print(f"{name} OK {len(df)}rows {time.time()-s:.1f}s")
        print(df.head(3).to_string()[:400])
    except Exception as e:
        print(f"{name} FAIL {str(e)[:150]}")
    print('---')

y = '20260902'
t('index_global(外盘指数日线)', lambda: pro.index_global(ts_code='IXIC', start_date='20260825', end_date=y))
t('global_closing(美股收盘概览)', lambda: pro.global_closing(trade_date=y))
t('fx_daily(美元指数)', lambda: pro.fx_daily(ts_code='XAUUSD.SGE', start_date='20260825', end_date=y) if False else pro.fx_ob_list())