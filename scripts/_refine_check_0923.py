import json, urllib.request
h = json.load(urllib.request.urlopen('http://127.0.0.1:8188/history', timeout=15))
import datetime
for pid, e in list(h.items())[-4:]:
    st = e.get('status', {})
    ts = e.get('prompt', [None])[0]
    outs = [(n, [im.get('filename') for im in o.get('images', [])]) for n, o in e.get('outputs', {}).items() if o.get('images')]
    print(pid[:8], st.get('status_str'), 'completed:', st.get('completed'), outs)
q = json.load(urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=15))
print('queue running:', len(q['queue_running']), 'pending:', len(q['queue_pending']))
