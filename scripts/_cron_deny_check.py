import json, os, glob, time

HOME = os.path.expanduser('~')
jobs = json.load(open(f'{HOME}/.hermes/cron/jobs.json'))
jl = jobs if isinstance(jobs, list) else jobs.get('jobs', jobs)
id2name = {j.get('id'): (j.get('name') or '?') for j in jl}

# 48h 内有输出文件的 job 目录
cutoff = time.time() - 48*3600
rows = []
for d in sorted(glob.glob(f'{HOME}/.hermes/cron/output/*/')):
    jid = os.path.basename(d.rstrip('/'))
    files = [f for f in glob.glob(d+'*') if os.path.getmtime(f) > cutoff and 'monitor' not in f]
    if not files:
        continue
    latest = max(files, key=os.path.getmtime)
    try:
        txt = open(latest, errors='replace').read()
    except Exception as e:
        rows.append((jid, id2name.get(jid,'?'), 'READ_ERR', ''))
        continue
    tail = txt[-1500:]
    # 判断迹象：明确无法执行 / 报告是否像完整收尾
    cannot = ('无法执行' in txt) or ('卡审批' in tail) or ('pending approval' in tail.lower())
    # 完整收尾迹象：含结论性段落或明确完成语
    done = any(k in tail for k in ['【我的判断', '已完成', '巡逻', '报告', 'DONE', 'OK', '成功', '收盘', '净值', '无新增', '静默', 'SILENT', '失败', 'WARN', 'FAIL'])
    rows.append((jid, id2name.get(jid,'?'), ('CANNOT!' if cannot else 'ok'), ('complete_tail' if done else 'TRUNC?')))

for r in sorted(rows, key=lambda x: x[2]):
    print(r[2], r[3], r[0], r[1])
print('total_dirs=', len(rows))
