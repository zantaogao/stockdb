@echo off
setlocal
cd /d %~dp0
if exist _done_c1.txt del _done_c1.txt
start /min "" cmd /c ""C:\Program Files\Python311\python.exe" -B train_v6_c1.py > train_v6_c1.log 2>&1 && echo DONE>> _done_c1.txt || echo FAIL>> _done_c1.txt"
echo SPAWNED train_v6_c1
endlocal
