import os, json, re
from collections import defaultdict

output_base = '/Users/zantao/.hermes/cron/output/'

all_outputs = {}
for root, dirs, files in os.walk(output_base):
    for f in sorted(files):
        if '2026-07-10' not in f:
            continue
        full_path = os.path.join(root, f)
        job_id = os.path.basename(os.path.dirname(full_path))

        try:
            with open(full_path, 'r', errors='replace') as fh:
                content = fh.read()

            lines = content.split('\n')
            actual_lines = []
            in_output = False

            for line in lines:
                if '## Output' in line or 'Output:' in line:
                    in_output = True
                    continue
                if in_output and line.strip():
                    # 跳过cron元数据行
                    stripped = line.strip()
                    if stripped.startswith('**') and ':' in stripped[:20]:
                        continue
                    if re.match(r'^(Schedule|Run Time|Job ID|Name):', stripped):
                        continue
                    actual_lines.append(stripped)

            result_text = ' '.join(actual_lines).strip()

            # 判断内容类型
            is_silent = '[SILENT]' in content or '无需处理' in result_text or '文件为空' in result_text
            has_real_content = len(result_text) > 50 and not is_silent

            if job_id not in all_outputs:
                all_outputs[job_id] = {'outputs': []}

            # 从文件名提取时间
            time_match = re.search(r'(\d+-\d+-\d+)_(\d+)-', f)
            t_str = ''
            hour = 0
            if time_match:
                date_part, hour_str = time_match.groups()
                hour = int(hour_str)
                t_str = f"{date_part} {hour:02d}:xx"

            all_outputs[job_id]['outputs'].append({
                'time': t_str,
                'hour': hour,
                'file': f,
                'content_preview': result_text[:150],
                'has_real_content': has_real_content,
                'is_silent': is_silent,
                'size': len(content)
            })
        except Exception as e:
            pass

# 汇总：每个job收盘后的执行情况和内容类型
print("=== 收盘后(>=15:xx)所有cron job执行情况 ===\n")

after_close_summary = defaultdict(lambda: {'count': 0, 'has_real': [], 'silent_count': 0})

for job_id, data in all_outputs.items():
    for out in data['outputs']:
        if out['hour'] >= 15:
            after_close_summary[job_id]['count'] += 1
            if out['is_silent']:
                after_close_summary[job_id]['silent_count'] += 1
            else:
                after_close_summary[job_id]['has_real'].append(out)

for job_id in sorted(after_close_summary.keys(), key=lambda x: -after_close_summary[x]['count']):
    s = after_close_summary[job_id]
    
    # 取job名称（从第一条输出提取）
    name_preview = ''
    if after_close_summary[job_id]['has_real']:
        name_preview = after_close_summary[job_id]['has_real'][0]['content_preview'][:100]
    
    print(f"Job: {job_id}")
    print(f"  收盘后执行次数: {s['count']} (其中Silent={s['silent_count']}, 有内容={len(s['has_real'])})")
    if s['has_real']:
        latest = s['has_real'][0]
        print(f"  最新内容预览: {latest['content_preview'][:200]}")
    else:
        print("  (全部是沉默/空消息)")
    print()
