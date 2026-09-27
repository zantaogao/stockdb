@echo off
setlocal
cd /d C:\Users\zantan\retrain_20260927
if exist _done_v8.txt del _done_v8.txt
"C:\Program Files\Python311\python.exe" -B train_v8.py > train_v8_win.log 2>&1
echo EXIT=%ERRORLEVEL%> _done_v8.txt
endlocal
