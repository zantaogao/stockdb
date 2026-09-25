#!/usr/bin/env python3
# 给 shadow_score_daily.py 加 __main__ 保护：
# 现象(09-06)：min_feat_lib 的 multiprocessing.Pool 在 macOS spawn 下把主脚本
# 从头重跑（脚本顶层直接执行、无保护），子进程再开 Pool → 无限套娃空转。
# 改法：import/常量区之后（从 "t0 = time.time()" 起）整体缩进进 if __name__ == '__main__': 块。
from pathlib import Path
import ast

p = Path('/Users/zantao/.hermes/stockdb/scripts/shadow_score_daily.py')
lines = p.read_text().splitlines(keepends=True)
anchor = "t0 = time.time()\n"
i = lines.index(anchor)
body = lines[i:]
guarded = ["if __name__ == '__main__':\n"]
for ln in body:
    guarded.append(('    ' + ln) if ln.strip() else ln)
out = ''.join(lines[:i] + guarded)
ast.parse(out)
p.write_text(out)
print('GUARD_ADDED at line', i + 1, 'total', len(lines), '->', len(guarded))