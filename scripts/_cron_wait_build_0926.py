"""构建完成等待器：轮询 build_v5fix.log 出现 DONE（或进程消失）后报告最终行。
用法: /usr/bin/python3 -B scripts/_cron_wait_build_0926.py
"""
import subprocess, time, os, glob

BASE = os.path.expanduser('~/.hermes/stockdb/analysis/retrain_20260926')
LOG = f'{BASE}/build_v5fix.log'
deadline = time.time() + 3600
while time.time() < deadline:
    try:
        txt = open(LOG, errors='ignore').read()
    except FileNotFoundError:
        txt = ''
    if 'FINAL' in txt or 'DONE' in txt:
        tail = [l for l in txt.strip().split('\n') if 'FINAL' in l or 'DONE' in l][-3:]
        print('BUILD_DONE:', tail, flush=True)
        break
    # 进程是否还活着
    out = subprocess.run(['pgrep', '-f', '_cron_retrain_build_0926'], capture_output=True, text=True)
    if not out.stdout.strip():
        print('BUILD_PROCESS_GONE. 日志尾:', txt.strip().split('\n')[-3:], flush=True)
        break
    time.sleep(60)
else:
    print('WAIT_TIMEOUT(60min). 日志尾:', open(LOG, errors='ignore').read().strip().split('\n')[-3:], flush=True)
