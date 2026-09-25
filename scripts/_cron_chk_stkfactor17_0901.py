import subprocess

p = subprocess.Popen(['/bin/bash', '/Users/zantao/.hermes/scripts/backfill_stk_factor.sh'],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
buf = b''
while True:
    b = p.stdout.read(1)
    if not b:
        break
    buf += b
    if b'\n' in buf:
        lines, buf = buf.split(b'\n'), buf
        for ln in lines:
            try:
                print(ln.decode('utf-8', errors='backslashreplace'))
            except Exception as e:
                print('DECODE FAIL:', repr(ln[:120]), e)
print('rc', p.wait())
# Also: does the raw byte stream contain 0xbc at abs position 42?
print('byte42 of full capture:', hex(open('/dev/null','rb').read(0) and 0) if False else '')