@echo off
setlocal
cd /d %~dp0
if exist _done.txt del _done.txt
start /min "" cmd /c ""C:\Program Files\Python311\python.exe" %1 > %2 2>&1 && echo DONE>> _done.txt || echo FAIL>> _done.txt"
echo SPAWNED %1
endlocal
