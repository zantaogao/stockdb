@echo off
setlocal
cd /d %~dp0
set RETRAIN_ONLY=%1
if "%RETRAIN_ONLY%"=="" set RETRAIN_ONLY=both
"C:\Program Files\Python311\python.exe" train.py > train_%RETRAIN_ONLY%.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> train_%RETRAIN_ONLY%.log
endlocal
