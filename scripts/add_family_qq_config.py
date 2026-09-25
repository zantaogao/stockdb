#!/usr/bin/env python3
"""config.yaml 加家庭成员 QQ bot 配置（2026-08-03）：
1. gateway.profile_routes: qqbot2/3/4 → family profile（平台级路由）
2. qqbot2/3/4 平台段（enabled: false 占位，凭据到位后填 app_id/secret 再 enabled）
"""
import yaml, shutil, sys
from datetime import datetime

PATH = '/Users/zantao/.hermes/config.yaml'
shutil.copy(PATH, f'{PATH}.bak.{datetime.now():%Y%m%d_%H%M%S}_qqfamily')

with open(PATH, encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

# 1. profile_routes（替换占位 '[]' 字符串或空）
routes = []
for key, name in [('qqbot2', 'family-qqbot2'), ('qqbot3', 'family-qqbot3'), ('qqbot4', 'family-qqbot4')]:
    routes.append({'name': name, 'platform': key, 'profile': 'family'})
gateway = cfg.setdefault('gateway', {})
gateway['multiplex_profiles'] = True
gateway['profile_routes'] = routes

# 2. qqbot2/3/4 平台段（占位）
members = {
    'qqbot2': '家人1',
    'qqbot3': '家人2',
    'qqbot4': '家人3',
}
for key, label in members.items():
    cfg[key] = {
        'enabled': False,  # 凭据到位后改 true
        'extra': {
            'app_id': '',          # TODO: 成员提供
            'client_secret': '',   # TODO: 成员提供
            'dm_policy': 'allowlist',
            'allow_from': [],      # TODO: 成员 openid
        },
    }

with open(PATH, 'w', encoding='utf-8') as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

print('✅ config.yaml 已更新（qqbot2/3/4 段 + profile_routes → family）')
print('   qqbot2/3/4 enabled: false（等成员凭据）')
