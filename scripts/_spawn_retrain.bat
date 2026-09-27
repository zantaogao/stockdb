@echo off
setlocal
cd /d C:\Users\zanta\retrain_20260926
if exist _done.txt del _done.txt
start /min "" cmd /c "call run.bat %1 > spawn_%1.log 2>&1 & echo R%ERRORLEVEL%>> _done.txt"
echo SPAWNED_%1
endlocal
