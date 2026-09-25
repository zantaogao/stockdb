# 测美元指数/美债10Y/布伦特原油 的国内直连取法
import subprocess

TESTS = [
    ("sina外汇-美元指数", "import urllib.request as u; print(u.urlopen('https://hq.sinajs.cn/list=fx_sxdci',timeout=15).read().decode('gbk'))"),
    ("sina美债10Y", "import urllib.request as u; print(u.urlopen('https://hq.sinajs.cn/list=gb_dji,fx_susdcn',timeout=15).read().decode('gbk')[:200])"),
    ("东财全球指数spot(em)", "import akshare as ak; df=ak.index_global_spot_em(); print(len(df)); print(df.head(5).to_string()[:400])"),
    ("新浪全球指数实时(sina)", "import akshare as ak; df=ak.index_global_hist_sina(symbol='美元指数'); print(df.tail(3).to_string()[:300])"),
    ("tushare-美元指数fx", "import tushare as ts,json; ts.set_token(json.load(open('/Users/zantao/.hermes/stockdb/config.json'))['tushare_token']); df=ts.pro_api().fx_daily(ts_code='USDX.FX',start_date='20260828',end_date='20260903'); print(df.head(3).to_string()[:300])"),
    ("东财期货spot含原油重跑", "import akshare as ak; df=ak.futures_global_spot_em(); d=df[df['名称'].str.contains('原油|布伦特|WTI|黄金|铜',na=False)]; print(len(df)); print(d.head(6).to_string()[:500])"),
]
LOG = open('/Users/zantao/.hermes/stockdb/scripts/_test_global4.log','a',buffering=1)
for name, code in TESTS:
    try:
        r = subprocess.run(['/usr/bin/python3','-B','-c',code], capture_output=True, text=True, timeout=45,
                           env={'PATH':'/usr/bin:/bin','HOME':'/Users/zantao'})
        LOG.write(f"=== {name}: {'OK' if r.returncode==0 else 'FAIL'}\n{(r.stdout.strip() or r.stderr.strip())[:500]}\n")
    except subprocess.TimeoutExpired:
        LOG.write(f"=== {name}: TIMEOUT\n")
LOG.write("=== ALL DONE\n")