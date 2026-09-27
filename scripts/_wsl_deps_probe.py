# WSL内直接执行: 训练依赖全检
import lightgbm as lgb, scipy, pyarrow, pandas, numpy
print("ALL_DEPS_OK", lgb.__version__, scipy.__version__, pyarrow.__version__)
