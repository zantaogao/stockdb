import json, glob, os
base = '/Users/zantao/.hermes/stockdb'
# do other accounts' JSON contain the 0916 cleanup sells?
samples = {'center_dual': ['000990','001256','688486'], 'fusion_center': ['000032','600841'], 'cmmr_fusion': ['605189']}
for f, codes in samples.items():
    d = json.load(open(f'{base}/sim_accounts/{f}.json'))
    hits = [t for t in d.get('trades', []) if str(t.get('date','')).replace('-','') == '20260916']
    print(f, 'JSON 0916 trades:', hits)
    print(f, 'positions of cleanup codes:', [(x.get('code'), x.get('shares')) for x in d.get('positions', []) if x.get('code') in codes])
    print(f, 'cash:', d.get('cash'))
