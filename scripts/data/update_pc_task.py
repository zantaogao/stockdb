import subprocess, sys
# Update the LSTMInference task to use v2 script
cmd = [
    'schtasks', '/CREATE', '/TN', 'LSTMInferV2', '/SC', 'DAILY',
    '/ST', '17:00',
    '/TR', r'"C:\Program Files\Python311\python.exe" "C:\Users\pumma\factor_lib\lstm_infer_v2.py"',
    '/F'
]
result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RC:", result.returncode)
