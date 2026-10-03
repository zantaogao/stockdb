import glob, os

HOME = os.path.expanduser('~')
ids = ['1bacebf749f1','3265f75f9af3','382340cfaf64','3f7866e772ec','489b7d201800',
'6a2da41b7677','6bf2957b6e1b','70573919e1aa','829ca8e08bda','9241c4978a5d',
'a1f9507068a1','a2878833be80','a54fe816d29c','ab0d2d507b44','e26411bc653e',
'e90d037af31b','edf1f13bdb60']
for jid in ids:
    files = sorted(glob.glob(f'{HOME}/.hermes/cron/output/{jid}/*'), key=os.path.getmtime)
    files = [f for f in files if 'monitor' not in f]
    if not files:
        print(jid, 'NO_OUTPUT'); continue
    latest = files[-1]
    txt = open(latest, errors='replace').read()
    bad = ('无法执行' in txt) or ('blocked' in txt.lower() and 'no_change' not in txt)
    tail = txt.strip()[-200:].replace('\n',' | ')
    print(jid, os.path.basename(latest), 'len=', len(txt), 'BAD' if bad else 'fine', '::', tail[:180])
