Set-Location C:\Users\zantan\retrain_20260926
if (Test-Path _done_c1.txt) { Remove-Item _done_c1.txt }
$p = Start-Process -FilePath 'C:\Program Files\Python311\python.exe' -ArgumentList '-B','train_v6_c1.py' -WorkingDirectory 'C:\Users\zantan\retrain_20260926' -WindowStyle Hidden -RedirectStandardOutput 'C:\Users\zantan\retrain_20260926\train_v6_c1.log' -RedirectStandardError 'C:\Users\zantan\retrain_20260926\train_v6_c1.err' -PassThru
Write-Output "PID=$($p.Id)"
