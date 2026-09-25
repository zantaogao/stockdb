from pathlib import Path
import ast
p = Path('/Users/zantao/.hermes/stockdb/scripts/shadow_score_daily.py')
s = p.read_text()
bad = [ln for ln in s.splitlines() if '\u2026' in ln]
assert bad, 'no ellipsis found'
for ln in bad:
    s = s.replace(ln, 'mf = min_feat_lib.min_feats_…rget)')
ast.parse(s)
p.write_text(s)
print('FIXED:', repr(bad[0]), '->', repr([l for l in s.splitlines() if 'min_feats_for_date' in l][0]))