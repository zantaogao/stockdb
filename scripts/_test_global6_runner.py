import subprocess
TESTS = [
    ("tushare道指代码变体", """
import tushare as ts,json
ts.set_token(json.load(open('/Users/zantao/.hermes/stockdb/config.json'))['tushare_token'])
pro=ts.pro_api()
for c in ['DJIA','DJI','KS11','FTSE','GDAXI','HSTECH','HSCEI','N225']:
    try:
        df=pro.index_global(ts_code=c,start_date='20260828',end_date='20260903')
        print(c,len(df), df.tail(1)[['close','pct_chg']].to_string() if len(df) else '')
    except Exception as e: print(c,'ERR',str(e)[:60])
"""),
    ("东财期货名称-原油布伦特", "import akshare as ak; df=ak.futures_global_spot_em(); print([n for n in df['名称'] if any(k in str(n) for k in ['原油','布伦特','WTI','富时','A50','美'] )][:20])"),
    ("东财全球指数名单全", "import akshare as ak; df=ak.index_global_spot_em(); print(df[['代码','名称']].to_string()[:2000])"),
]
LOG = open('/Users/zantao/.hermes/stockdb/scripts/_test_global6.log','a',buffering=1)
for name, code in TESTS:
    try:
        r = subprocess.run(['/usr/bin/python3','-B','-c',code], capture_output=True, text=True, timeout=60,
                           env={'PATH':'/usr/bin:/bin','HOME':'/Users/zantao'})
        LOG.write(f"=== {name}: {'OK' if r.returncode==0 else 'FAIL'}\n{(r.stdout.strip() or r.stderr.strip())[-1500:]}\n")
    except subprocess.TimeoutExpired:
        LOG.write(f"=== {name}: TIMEOUT\n")
LOG.write("=== ALL DONE\n")