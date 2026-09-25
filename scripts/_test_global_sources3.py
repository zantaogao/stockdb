# 测试3: 无梯子可用的 akshare sina/cls 系接口（每个单独限时靠 socket 超时）
import socket
socket.setdefaulttimeout(20)
import akshare as ak

def t(name, fn):
    try:
        s = __import__('time').time()
        df = fn()
        print(f"{name} OK {len(df)}rows {__import__('time').time()-s:.1f}s")
        print(df.head(3).to_string()[:300])
    except Exception as e:
        print(f"{name} FAIL {str(e)[:120]}")
    print('---', flush=True)

t('环球市场快讯-sina', lambda: ak.stock_info_global_sina())
t('财联社快讯-cls全部', lambda: ak.stock_info_global_cls(symbol="全部"))
t('同花顺快讯-ths', lambda: ak.stock_info_global_ths())
t('美股指数日线-sina .IXIC', lambda: ak.index_us_stock_sina(symbol=".IXIC"))
t('美股指数日线-sina .DJI', lambda: ak.index_us_stock_sina(symbol=".DJI"))
t('全球指数历史-sina', lambda: ak.index_global_hist_sina(symbol="上证指数") if False else ak.index_global_name_table())