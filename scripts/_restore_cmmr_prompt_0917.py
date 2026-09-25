# 2026-09-17 用户拍板：恢复 cmmr 系推送+进报告——清掉两个 cron prompt 里的停推指令
# 备份 jobs.json 后原位替换；改完重新读回验证
import json, shutil

P = '/Users/zantao/.hermes/cron/jobs.json'
BAK = P + '.bak.20260917_cmmr'
shutil.copy2(P, BAK)
print('备份:', BAK)

d = json.load(open(P))
jobs = d if isinstance(d, list) else d.get('jobs', [])
n = 0
for j in jobs:
    p = j.get('prompt') or ''
    if 'CMMR' not in p:
        continue
    orig = p
    if j['id'] == 'ee38c4107fbe':
        p = p.replace(
            '四榜共约40票（2026-09-11 起 CMMR 两榜已停推剔除）',
            '六榜共约60票（2026-09-17 恢复 CMMR独立/CMMR+三模型融合 两榜）')
        p = p.replace(
            '注意（2026-09-11 用户拍板）：CMMR 系（CMMR独立 cmmr、CMMR+融合 cmmr_fusion）全通道停推——报告正文一律不出现其名单/收益/IC/超额，draft 里若出现也删掉不提（账户照常运行）。',
            '注意（2026-09-17 用户拍板）：恢复 CMMR 系（CMMR独立 cmmr、CMMR+融合 cmmr_fusion）进报告——名单/收益/IC/超额正常写入正文，与其余账户同权对待；两账户历史超额曾因基准口径虚高约3pp，已于09-17修正基准（tushare中证1000官方收盘价），以修正后数字为准。')
    elif j['id'] == '6bcc281a869f':
        p = p.replace(
            '逐榜（三模型融合/中枢版Top10/中枢版+三模型/10d独立）',
            '逐榜（三模型融合/CMMR独立/CMMR+三模型融合/中枢版Top10/中枢版+三模型/10d独立）')
        p = p.replace('；2026-09-11 起 CMMR 两榜停推剔除', '；2026-09-17 恢复 CMMR 两榜')
        p = p.replace('；2026-09-11 起 CMMR两榜停推剔除', '；2026-09-17 恢复 CMMR 两榜')
    if p != orig:
        j['prompt'] = p
        n += 1
        print(f"改: {j['id']} {j.get('name')}")

json.dump(d, open(P, 'w'), ensure_ascii=False, indent=2)

# 读回验证
d2 = json.load(open(P))
jobs2 = d2 if isinstance(d2, list) else d2.get('jobs', [])
ok = True
for j in jobs2:
    p = j.get('prompt') or ''
    if '停推' in p and 'CMMR' in p:
        print('残留停推指令:', j['id'])
        ok = False
print('共改', n, '个任务; 残留检查:', '干净' if ok else '有残留')
