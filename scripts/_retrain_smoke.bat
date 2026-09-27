@echo off
setlocal
cd /d %~dp0
set OMP_NUM_THREADS=8
set LIGHTGBM_THREADS=8
set OMP_THREAD_LIMIT=1
"C:\Program Files\Python311\python.exe" smoke_train.py > smoke.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> smoke.log
endlocal
