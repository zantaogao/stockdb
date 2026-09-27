# v6b 训练拉起 v4: PowerShell 脚本文件上传执行（避开变量名/引号剥层）
import subprocess, time
def sh(cmd):
    r=subprocess.run(['ssh','zantan@192.168.3.168',cmd],capture_output=True)
    return r.stdout.decode('gbk',errors='replace')+r.stderr.decode('gbk',errors='replace')
ps = """Set-Location 'C:\\Users\\zantan\\retrain_20260926'
Remove-Item train_v6b.log,train_v6b.err,_done_v6.txt -ErrorAction SilentlyContinue
$p = Start-Process -FilePath 'C:\\Program Files\\Python311\\python.exe' -ArgumentList '-B','train_v6b.py' -WorkingDirectory 'C:\\Users\\zantan\\retrain_20260926' -WindowStyle Minimized -PassThru -RedirectStandardOutput 'train_v6b.log' -RedirectStandardError 'train_v6b.err'
Write-Output ("SPAWNED_PID=" + $p.Id)
"""
open('/tmp/spawn_v6b.ps1','w',newline='\r\n').write(ps)
subprocess.run(['scp','-q','/tmp/spawn_v6b.ps1','zantan@192.168.3.168:C:/Users/zantan/retrain_20260926/spawn_v6b.ps1'],check=True)
print(sh('powershell -ExecutionPolicy Bypass -File C:\\Users\\zantan\\retrain_20260926\\spawn_v6b.ps1'))
time.sleep(30)
print(sh('tasklist /FI "IMAGENAME eq python.exe" /FO CSV'))
print('--log--', sh('type C:\\Users\\zantan\\retrain_20260926\\train_v6b.log')[:300])
print('--err--', sh('type C:\\Users\\zantan\\retrain_20260926\\train_v6b.err')[:300])
