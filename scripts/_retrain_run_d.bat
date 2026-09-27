@echo off
setlocal
cd /d %~dp0
set RETRAIN_DIR=D:\retrain
if not exist D:\retrain mkdir D:\retrain
set LOG=D:\retrain\train_%1.log
if "%1"=="" set LOG=D:\retrain\train_all.log
if "%1"=="" (set RETRAIN_ONLY=both) else (set RETRAIN_ONLY=%1)
if exist D:\retrain\_done.txt del D:\retrain\_done.txt
"C:\Program Files\Python311\python.exe" train.py > "%LOG%" 2>&1
echo EXIT=%ERRORLEVEL%> D:\retrain\_done.txt
endlocal
