@echo off
setlocal
cd /d C:\Users\zanta\retrain_20260926
set OMP_NUM_THREADS=8
set LIGHTGBM_THREADS=8
"C:\Program Files\Python311\python.exe" train_probe.py > probe.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> probe.log
endlocal
