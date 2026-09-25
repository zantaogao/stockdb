#!/usr/bin/env python3
"""查 cron jobs.json：盘前/盘后两条报告任务的 delivery target + prompt 里是否含 push 脚本。"""
import json, os

p = os.path.expanduser('~/.hermes/cron/jobs.json')
d = json.load(open(p))
jobs = d if isinstance(d, list) else d.get('jobs', d)
if isinstance(jobs, dict):
    jobs = list(jobs.values())
for j in jobs:
    txt = json.dumps(j, ensure_ascii=False)
    if '_cron_push' in txt or '盘后' in txt or '盘前' in txt:
        print('---')
        print('id      :', j.get('id'))
        print('name    :', j.get('name'))
        print('schedule:', j.get('schedule'))
        print('enabled :', j.get('enabled'))
        print('target  :', j.get('target'), '| platform:', j.get('platform'), '| chat_id:', j.get('chat_id'))
        for k in ('deliver_to', 'delivery', 'destination', 'notify_target', 'deliver'):
            if k in j:
                print('%s: %s' % (k, j[k]))
        pr = json.dumps(j.get('prompt', ''), ensure_ascii=False)
        print('prompt has _cron_push:', '_cron_push' in pr)
