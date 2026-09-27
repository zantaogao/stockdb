# spawn v6b 修正版: cmd /c "(python ... & echo R%ERRORLEVEL%)" 括号分组确保done标记在子进程退出后写入
import subprocess, time
bat = "@echo off\r\nsetlocal\r\ncd /d C:\\Users\\zantan\\retrain_20260926\r\nif exist _done_v6.txt del _done_v6.txt\r\nif exist train_v6b.log del train_v6b.log\r\nstart /min \"\" cmd /c \"\"( \"C:\\Program Files\\Python311\\python.exe\" -B train_v6b.py > train_v6b.log 2>&1 & echo R%ERRORLEVEL% )>> _done_v6.txt\" \r\necho SPAWNED_v6b\r\n"
open('/tmp/spawn_v6b.bat','w',newline='').write(bat)
subprocess.run(['scp','-q','/tmp/spawn_v6b.bat','zantan@192.168.3.168:C:/Users/zantan/retrain_20260926/spawn_v6b.bat'],check=True)
r=subprocess.run(['ssh','zantan@192.168.3.168','cmd /c C:\\Users\\zantan\\retrain_20260926\\spawn_v6b.bat'],capture_output=True)
print('spawn out:', r.stdout.decode('gbk',errors='replace'))
time.sleep(20)
def sh(cmd):
    rr=subprocess.run(['ssh','zantan@192.168.3.168',cmd],capture_output=True)
    return rr.stdout.decode('gbk',errors='replace')
print(sh('tasklist /FI "IMAGENAME eq python.exe" /FO CSV'))
print('log头:', sh('type C:\\Users\\zantan\\retrain_20260926\\train_v6b.log')[:300])
