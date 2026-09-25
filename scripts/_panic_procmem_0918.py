import re
raw = open('/Library/Logs/DiagnosticReports/panic-full-2026-09-18-214156.0002.panic').read()
entries = re.findall(r'"procname"\s*:\s*"([^"]+)"[^{}]*?"residentMemoryBytes"\s*:\s*(\d+)', raw)
if len(entries) < 20:
    # order may be reversed
    entries2 = re.findall(r'"residentMemoryBytes"\s*:\s*(\d+)[^{}]*?"procname"\s*:\s*"([^"]+)"', raw)
    entries = [(n, v) for v, n in entries2] + entries
agg = {}
for name, v in entries:
    v = int(v)
    agg[name] = max(agg.get(name, 0), v)
for name, v in sorted(agg.items(), key=lambda x: -x[1])[:15]:
    print(f"{v/2**30:7.1f} GB  {name}")
print("total procs:", len(agg))
tr = [n for n in agg if re.search(r'rsync|scp|sftp|tar|ssh|curl|afp|smb|net', n, re.I)]
print("transfer-ish:", tr)
