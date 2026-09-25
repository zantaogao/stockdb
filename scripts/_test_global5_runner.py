import subprocess
TESTS = [
    ("em全球指数-点名查", "import akshare as ak; df=ak.index_global_spot_em(); d=df[df['名称'].str.contains('道|标普|纳|日经|恒生|富时|DAX|德国|法国',na=False)]; print(d[['代码','名称','最新价','涨跌幅','最新行情时间']].to_string()[:1500])"),
    ("em期货-主力原油黄金铜", "import akshare as ak; df=ak.futures_global_spot_em(); d=df[df['名称'].isin(['原油2709','伦敦铜','伦敦金','布伦特原油','WTI原油','纽约原油','COMEX黄金','COMEX铜'])]; print(d.to_string()[:800]); print('名称样例:', df['名称'].head(30).tolist())"),
    ("东财全球指数历史-道指", "import akshare as ak; df=ak.index_global_hist_em(symbol='道琼斯'); print(df.tail(3).to_string()[:400])"),
]
LOG = open('/Users/zantao/.hermes/stockdb/scripts/_test_global5.log','a',buffering=1)
for name, code in TESTS:
    try:
        r = subprocess.run(['/usr/bin/python3','-B','-c',code], capture_output=True, text=True, timeout=60,
                           env={'PATH':'/usr/bin:/bin','HOME':'/Users/zantao'})
        LOG.write(f"=== {name}: {'OK' if r.returncode==0 else 'FAIL'}\n{(r.stdout.strip() or r.stderr.strip())[-600:]}\n")
    except subprocess.TimeoutExpired:
        LOG.write(f"=== {name}: TIMEOUT\n")
LOG.write("=== ALL DONE\n")