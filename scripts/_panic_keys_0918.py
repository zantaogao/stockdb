import re
raw = open('/Library/Logs/DiagnosticReports/panic-full-2026-09-18-214156.0002.panic').read()
# find key names containing 'memo' or 'resident'
keys = set(re.findall(r'"(\w*(?:memo|resident|phys|footprint)\w*)"\s*:', raw, re.I))
print("mem-ish keys:", keys)
# sample one big entry: find mlx-serve procname and print surrounding keys
i = raw.find('"mlx-serve"')
print("mlx ctx found at", i)
if i > 0:
    seg = raw[max(0,i-3000):i+3000]
    for k in sorted(set(re.findall(r'"(\w+)"\s*:', seg))):
        print(k, end=' ')
    print()
