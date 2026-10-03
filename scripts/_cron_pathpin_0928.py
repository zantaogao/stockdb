"""批量给 ~/.hermes/scripts/*.sh 生产脚本钉 PATH（0928 环境漂移事故）。
规则: 有裸 python3 调用且没有 export PATH 钉制的，在 shebang+注释头之后插入
export PATH="/usr/bin:$PATH"（与 update_tushare_api.sh 同款先例）。
一次性脚本(_cron_*)跳过。幂等。"""
import glob, os, re

PIN = 'export PATH="/usr/bin:$PATH"   # 0928环境漂移: cron裸python3曾随hermes工具链切换丢duckdb/tushare'
targets = []
for f in sorted(glob.glob(os.path.expanduser("~/.hermes/scripts/*.sh"))):
    base = os.path.basename(f)
    if ".bak" in base or base.startswith("_cron_"):
        continue
    txt = open(f, errors="replace").read()
    if "export PATH" in txt:
        continue
    lines = txt.splitlines(keepends=True)
    if not any(re.search(r"(?<![\w/])python3(\s+-B|\s+-c|\s+[-\w])", l) and not l.strip().startswith("#") and "/usr/bin/python3" not in l for l in lines):
        continue
    # 插入点: shebang 后跳过连续注释行
    i = 1
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        i += 1
    lines.insert(i, PIN + "\n")
    with open(f, "w") as fh:
        fh.writelines(lines)
    targets.append(base)

print("已钉 PATH:", len(targets))
for t in targets: print(" ", t)
