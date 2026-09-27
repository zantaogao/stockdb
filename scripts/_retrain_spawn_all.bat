@echo off
setlocal
cd /d D:\retrain
if exist _done.txt del _done.txt
if exist out\lgb_reg_10d_v5.txt del out\lgb_reg_10d_v5.txt
if exist out\lgb_reg_20d_v2.txt del out\lgb_reg_20d_v2.txt
if exist out\lgb_reg_40d_v5.txt del out\lgb_reg_40d_v5.txt
start /min "retrain_all" cmd /c ""C:\Program Files\Python311\python.exe" train.py 1> train_all.log 2>&1 & echo EXIT=%ERRORLEVEL%> _done.txt"
echo SPAWNED_ALL
endlocal
