@echo off
setlocal
cd /d %~dp0
if exist _done.txt del _done.txt
if exist lgb_reg_10d_v5.txt del lgb_reg_10d_v5.txt
if exist v10_v5_stats.json del v10_v5_stats.json
if exist daily_ic_10d_v5.csv del daily_ic_10d_v5.csv
if exist train_10d_v5_results.json del train_10d_v5_results.json
set RETRAIN_ONLY=10d
start /min "retrain10d" cmd /c ""C:\Program Files\Python311\python.exe" train.py 1> train_10d.log 2>&1 & echo EXIT=%ERRORLEVEL%>> _done.txt"
echo SPAWNED_10D
endlocal
