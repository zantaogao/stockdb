import json
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
def walk(j, path=''):
    if isinstance(j, dict):
        s = json.dumps(j, ensure_ascii=False)
        if 'signal_agent' in s or '评分' in s or 'health_check' in s:
            print('--- FOUND at', path, '---')
            print(s[:1500])
        for k, v in j.items():
            walk(v, path + '/' + k)
    elif isinstance(j, list):
        for i, v in enumerate(j):
            walk(v, path + f'[{i}]')
walk(d)
