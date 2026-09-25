# 逐接口测试（结果实时追加写入 _test_global3.log，单接口用子进程隔离+超时）
import subprocess, sys, json

TESTS = [
    ("快讯-sina全球", "import akshare as ak; df=ak.stock_info_global_sina(); print(len(df)); print(df.head(2).to_string()[:300])"),
    ("快讯-cls", "import akshare as ak; df=ak.stock_info_global_cls(symbol='全部'); print(len(df)); print(df.head(2).to_string()[:300])"),
    ("快讯-ths", "import akshare as ak; df=ak.stock_info_global_ths(); print(len(df)); print(df.head(2).to_string()[:300])"),
    ("美股指数-DJI-sina", "import akshare as ak; df=ak.index_us_stock_sina(symbol='.DJI'); print(len(df)); print(df.tail(2).to_string()[:300])"),
    ("全球指数名单", "import akshare as ak; df=ak.index_global_name_table(); print(len(df)); print(df.head(5).to_string()[:400])"),
    ("期货全球spot-em", "import akshare as ak; df=ak.futures_global_spot_em(); print(len(df)); print(df.head(3).to_string()[:400])"),
    ("全球指数spot-em", "import akshare as ak; df=ak.index_global_spot_em(); print(len(df)); print(df.head(3).to_string()[:400])"),
]

LOG = open('/Users/zantao/.hermes/stockdb/scripts/_test_global3.log', 'a', buffering=1)
for name, code in TESTS:
    try:
        r = subprocess.run(['/usr/bin/python3', '-B', '-c', code],
                           capture_output=True, text=True, timeout=45)
        out = (r.stdout.strip() or r.stderr.strip())[:400]
        LOG.write(f"=== {name}: {'OK' if r.returncode==0 else 'FAIL'}\n{out}\n")
    except subprocess.TimeoutExpired:
        LOG.write(f"=== {name}: TIMEOUT 45s\n")
LOG.write("=== ALL DONE\n")