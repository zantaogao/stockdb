#!/usr/bin/env python3
"""920（北交所）5min 补拉重试（stockdb 治理 Task 2.1，五问定案⑤）。
每晚跑 failed.txt 全量：串行、每票后 sleep 2s 低调限流；成功→写 parquet + 从 failed 移除；
空结果/异常→留到明晚。failed 清零或连续 7 天有残余由健康检查项推 QQ。
用法: /usr/bin/python3 -B _cron_backfill_920_0925.py [每晚票数上限, 默认200]
"""
import sys, time, os
from pathlib import Path
import baostock as bs
import pandas as pd

BASE = Path(os.path.expanduser("~/.hermes/stockdb/minutes"))
FAILED = BASE / "failed.txt"
OUT = BASE / "5min"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 200

def load_failed():
    if not FAILED.exists(): return []
    return [ln.split("\t")[0].strip() for ln in FAILED.read_text().splitlines() if ln.strip()]

fails = load_failed()
print(f"待补 {len(fails)} 只，本晚上限 {LIMIT}")
if not fails:
    raise SystemExit(0)

lg = bs.login()
assert lg.error_code == "0", lg.error_msg
ok = 0; still = []
for i, code in enumerate(fails[:LIMIT]):
    try:
        rs = bs.query_history_k_data_plus(
            code, "date,time,code,open,high,low,close,volume,amount,adjustflag",
            frequency="5", start_date="2025-04-08", end_date="2099-12-31")
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            df = pd.DataFrame(rows, columns=rs.fields.split(","))
            safe = code.replace(".", "_")
            df.to_parquet(OUT / f"{safe}.parquet")
            ok += 1
        else:
            still.append(code + "\tempty result (likely rate-limited)")
    except Exception as e:
        still.append(code + "\t" + str(e)[:60])
    time.sleep(2)

# 重写 failed：本晚处理段用结果替换，未处理段保留
rest = fails[LIMIT:]
FAILED.write_text("\n".join(still + rest) + ("\n" if (still or rest) else ""))
bs.logout()
print(f"DONE ok={ok} fail={len(still)} remaining={len(still)+len(rest)}")
