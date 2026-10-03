import subprocess, glob, os, time
cands = glob.glob('/Users/zantao/.hermes/stockdb/orders/*') + glob.glob('/Users/zantao/.hermes/stockdb/**/pending*.json', recursive=True)
for f in sorted(set(cands), key=os.path.getmtime):
    print(time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f)
