# 本机 mlx_lm 0.29.1 是否支持 qwen4_exp 架构（RVN 自转 MLX 可行性）
import pkgutil, os, inspect
import mlx_lm.models as M
names = sorted(m.name for m in pkgutil.iter_modules([os.path.dirname(M.__file__)]))
print('支持架构数:', len(names))
...<truncated>