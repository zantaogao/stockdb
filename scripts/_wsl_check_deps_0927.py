# WSL训练环境验证: lightgbm/scipy/pyarrow是否全部可用
import subprocess
def sh(cmd, t=120):
    r=subprocess.run(['ssh','-n','zantan@192.168.3.168',cmd],capture_output=True,timeout=t)
    return r.stdout.decode('gbk',errors='replace')+r.stderr.decode('gbk',errors='replace')
py = 'import lightgbm as lgb, scipy, pyarrow, pandas, numpy; print("ALL_DEPS_OK", lgb.__version__, scipy.__version__)'
print(sh("wsl.exe -e bash -c 'python3 -c \"" + py + "\" 2>&1 | tail -2'"))
