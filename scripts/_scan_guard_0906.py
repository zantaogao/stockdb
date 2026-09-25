import sys
sys.path.insert(0, '/Users/zantao/.hermes/hermes-agent')
from cron import lifecycle_guard as lg

orig_iter = lg._iter_referenced_shell_scripts
orig_read = lg._read_referenced_script
orig_direct = lg._direct_lifecycle_scan

def iter_patched(command, *, cwd=None):
    paths = list(orig_iter(command, cwd=cwd))
    print(f'ITER(depth) cwd={cwd} -> {[str(p) for p in paths]}')
    return iter(paths)

def read_patched(path):
    text, unsafe = orig_read(path)
    print(f'READ {path} unsafe={unsafe} size={len(text) if text else None}')
    return text, unsafe

def direct_patched(text):
    r = orig_direct(text)
    snippet = (text.strip().splitlines() or ['(empty)'])[0][:60]
    print(f'DIRECT -> {r} firstline={snippet!r}')
    return r

lg._iter_referenced_shell_scripts = iter_patched
lg._read_referenced_script = read_patched
lg._direct_lifecycle_scan = direct_patched

script = open('/Users/zantao/.hermes/scripts/min5_nightly.sh').read()
combined = '分钟线夜间链\n' + script
print('FINAL:', lg._contains_unsafe_gateway_action(combined, cwd='/Users/zantao/.hermes/scripts', depth=0, visited=set()))