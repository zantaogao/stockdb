# spawn v6_c1训练: wsl.exe -u root, setsid脱离会话
import subprocess
cmd = ('wsl.exe -u root -e bash -c '
       '"nohup setsid bash -c \\"/usr/bin/python3 /mnt/c/Users/zantan/retrain_20260926/train_v6_c1.py '
       '> /mnt/c/Users/zantan/retrain_20260926/train_v6_c1.log 2>&1; echo DONE_EXIT=$? '
       '>> /mnt/c/Users/zantan/retrain_20260926/train_v6_c1.log\\" < /dev/null > /dev/null 2>&1 & echo SPAWNED"')
r = subprocess.run(['ssh', '-n', 'zantan@192.168.3.168', cmd], capture_output=True, timeout=60)
print(r.stdout.decode('gbk', errors='replace'), r.stderr.decode('gbk', errors='replace'))
