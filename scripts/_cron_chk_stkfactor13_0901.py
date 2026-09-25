import subprocess

# Reproduce tonight's script run, capture raw bytes
p = subprocess.run(['/bin/bash', '/Users/zantao/.hermes/scripts/backfill_stk_factor.sh'],
                   capture_output=True, timeout=60)
raw = p.stdout
try:
    raw.decode('utf-8')
    print('stdout decodes fine, len', len(raw))
except UnicodeDecodeError as e:
    print('DECODE ERR at', e.start)
    print('bytes 0-100:', raw[:100])
    print('context:', raw[max(0,e.start-40):e.start+40])
print('rc', p.returncode)
print('stderr tail:', p.stderr[-500:].decode('utf-8', errors='replace'))