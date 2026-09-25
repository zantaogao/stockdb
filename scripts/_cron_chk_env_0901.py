# What environment does the cron scheduler use for scripts? sys.executable check.
import sys, shutil
print('sys.executable:', sys.executable)
print('which python3 (PATH):', shutil.which('python3'))
try:
    from tools.environments.local import build_subprocess_env
    env = build_subprocess_env()
    print('PATH given to cron scripts:', env.get('PATH', 'NO PATH')[:300])
    print('VIRTUAL_ENV:', env.get('VIRTUAL_ENV'))
except Exception as e:
    print('build_subprocess_env ERR', e)
# and does that python have duckdb?
import subprocess
for py in [shutil.which('python3')]:
    r = subprocess.run([py, '-c', 'import duckdb; print(duckdb.__version__)'], capture_output=True, text=True)
    print(py, '->', r.stdout.strip() or r.stderr.strip()[:100])