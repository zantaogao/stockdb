import subprocess
TESTS = [
    ("tushare us_daily 英伟达", """
import tushare as ts,json
ts.set_token(json.load(open('/Users/zantao/.hermes/stockdb/config.json'))['tushare_token'])
df=ts.pro_api().us_daily(ts_code='NVDA.O',start_date='20260828',end_date='20260903')
print(len(df)); print(df.head(3).to_string()[:300])
"""),
    ("东财期货名单-A50/中概相关", "import akshare as ak; df=ak.futures_global_spot_em(); print([n for n in df['名称'] if any(k in str(n) for k in ['A50','富时','中国','H'] )][:15])"),
    ("ak 美股个股日线 sina NVDA", "import akshare as ak; df=ak.stock_us_daily(symbol='NVDA'); print(len(df)); print(df.tail(2).to_string()[:250])"),
    ("ak 中概金龙指数", "import akshare as ak; df=ak.stock_us_spot_em(); d=df[df['名称'].str.contains('纳指|金龙|中国',na=False)]; print(len(df)); print(d.head(5).to_string()[:300])"),
    ("ak A50期货历史", "import akshare as ak; import akshare.futures as f; print([n for n in dir(ak) if 'a50' in n.lower() or 'cha50' in n.lower()])"),
]
LOG = open('/Users/zantao/.hermes/stockdb/scripts/_test_pre_extra.log','a',buffering=1)
for name, code in TESTS:
    try:
        r = subprocess.run(['/usr/bin/python3','-B','-c',code], capture_output=True, text=True, timeout=60,
                           env={'PATH':'/usr/bin:/bin','HOME':'/Users/zantao'})
        LOG.write(f"=== {name}: {'OK' if r.returncode==0 else 'FAIL'}\n{(r.stdout.strip() or r.stderr.strip())[-400:]}\n")
    except subprocess.TimeoutExpired:
        LOG.write(f"=== {name}: TIMEOUT 60s\n")
LOG.write("=== ALL DONE\n")