import os, socket, getpass, hashlib, time, psutil
BASE = os.path.dirname(os.path.abspath(__file__))
lines = []
lines.append(f'host={socket.gethostname()} user={getpass.getuser()} pid={os.getpid()} t={time.time()}')
lines.append(f'cwd={os.getcwd()} base={BASE}')
p = os.path.join(BASE, 'samples_20d.parquet')
h = hashlib.md5(open(p, 'rb').read(1_000_000)).hexdigest()
lines.append(f'samples_20d head-md5={h} size={os.path.getsize(p)}')
lines.append(f'cpu={psutil.cpu_count()} mem={psutil.virtual_memory().total/2**30:.0f}G avail={psutil.virtual_memory().available/2**30:.1f}G')
for d in ('C:\\', 'D:\\', 'E:\\', 'F:\\', 'G:\\'):
    if os.path.exists(d):
        u = psutil.disk_usage(d)
        lines.append(f'disk {d} total={u.total/2**30:.0f}G free={u.free/2**30:.0f}G')
open(os.path.join(BASE, 'probe_out.txt'), 'w').write('\n'.join(lines))
print('PROBE_DONE')
