import subprocess, socket, glob, os, json
# NAS 是否在线（只探测不写）
for h in ['NASGZT.local','192.168.3.199']:
    try:
        ip = socket.gethostbyname(h)
        s = socket.socket(); s.settimeout(3)
        r = s.connect_ex((ip, 22)); s.close()
        print(h, ip, 'ssh_port', 'OPEN' if r==0 else 'CLOSED')
    except Exception as e:
        print(h, 'ERR', e)
# cron jobs 里 NAS 任务状态
try:
    jobs = json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')))
    js = jobs if isinstance(jobs, list) else jobs.get('jobs', list(jobs.values()) if isinstance(jobs,dict) else [])
    for j in js:
        jj = j if isinstance(j, dict) else {}
        if 'NAS' in str(jj.get('name','')) or 'nas' in str(jj.get('name','')).lower():
            print({k: jj.get(k) for k in ('id','name','schedule','last_status','last_run','next_run') if k in jj})
except Exception as e:
    print('jobs.json ERR', e)
