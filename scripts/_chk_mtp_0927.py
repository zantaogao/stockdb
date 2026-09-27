# 查我们生产模型: 专家是否砍过 + MTP头是否在
import json, re
D = '/Users/zantao/models/Qwen3.8-Flash-Next-Uncensored-MLX-Serve-4bit/'
wm = json.load(open(D + 'model.safetensors.index.json')).get('weight_map', {})
...[truncated]