# v6b 训练拉起 v3: PowerShell Start-Process 直起 python，日志落 train_v6b.log，退出码落 _done_v6.txt
import subprocess, time
def sh(cmd):
    r=subprocess.run(['ssh','zantan@192.168.3.168',cmd],capture_output=True)
    return r.stdout.decode('gbk',errors='replace')+r.stderr.decode('gbk',errors='replace')
ps = (
  "Set-Location 'C:\\Users\\zantan\\retrain_20260926'; "
  "Remove-Item train_v6b.log,_done_v6.txt -ErrorAction SilentlyContinue; "
  "$p = Start-Process -FilePath 'C:\\Program Files\\Python311\\python.exe' "
  "-ArgumentList '-B','train_v6b.py' -WorkingDirectory 'C:\\Users\\zantan\\retrain_20260926' "
  "-WindowStyle Minimized -PassThru -RedirectStandardOutput 'train_v6b.log' -RedirectStandardError 'train_v6b.err'; "
  "$pid = $p.Id; \"SPAWNED_PID=$pid\""
)
print(sh('powershell -Command "'+ps+'"'))
time.sleep(25)
print(sh('tasklist /FI "IMAGENAME eq python.exe" /FO CSV'))
print('--log--', sh('type C:\\Users\\zantan\\retrain_20260926\\train_v6b.log')[:300])
print('--err--', sh('type C:\\Users\\zantan\\retrain_20260926\\train_v6b.err')[:300])
