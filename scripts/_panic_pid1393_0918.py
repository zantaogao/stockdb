import re
raw = open('/Library/Logs/DiagnosticReports/panic-full-2026-09-18-214156.0002.panic').read()
i = raw.find('"1393" :')
seg = raw[i:i+2600]
for k in ["procname","residentMemoryBytes","pageFaults","pageIns","userTimeTask","systemTimeTask","name","dispatch_queue_label","state"]:
    m = re.search(r'"%s"\s*:\s*("?[^,}]*"?)' % k, seg)
    print(k, "=", m.group(1) if m else None)
# also try: some reports carry argv under a separate taskList section
for pat in ["argv","executablePath","bundleID"]:
    hits = re.findall(r'"%s"\s*:\s*"([^"]{1,160})"' % pat, raw)
    print(pat, "count:", len(hits))
