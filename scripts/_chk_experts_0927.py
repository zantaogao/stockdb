import json
D = '/Users/zantao/models/Qwen3.8-Flash-Next-Uncensored-MLX-Serve-4bit/'
wm = json.load(open(D + 'model.safetensors.index.json')).get('weight_map', {})

# 看任意 expert 相关 key 长什么样
ek = [k for k in wm if '.experts.' in k]
print('contai...[truncated]