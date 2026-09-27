import json
seen = set()
rows = []
for f in ['/tmp/h1.json', '/tmp/h2.json']:
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f, 'ERR', e)
        conti...[truncated]