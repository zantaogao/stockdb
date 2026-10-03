import glob, os, time
for f in glob.glob('/Users/zantao/.hermes/stockdb/core/*.json'):
    print(f)
print('---')
for pat in ('account*.json','main_account*','portfolio*'):
    for f in glob.glob('/Users/zantao/.hermes/stockdb/**/'+pat, recursive=True):
        if os.path.getmtime(f) > time.time() - 8*86400:
            print(time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f)
