@echo off
setlocal
cd /d %~dp0
if exist D:\retrain\_done.txt del D:\retrain\_done.txt
if exist D:\retrain\train_10d.log del D:\retrain\train_10d.log
start /min "" cmd /c "rund.bat 10d"
echo SPAWNED_10D_VIA_START
endlocal
