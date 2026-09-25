# -*- coding: utf-8 -*-
"""Task 3.4 v2 补丁：装饰器改继承 BaseDataSource（非包装委托）。
实锤：main.py:151 在 mod.start_up 之后才建数据源，但 AbstractDataSource 基类
get_trading_calendars 抛 NotImplementedError——包装类的 __getattr__ 只在属性缺失时触发，
基类已定义该属性 → 委托失效。继承 + super() 委托才可靠。
"""
src = open('rqalpha_mod_stockdb_min.py').read()

old = '''class MinuteOverlayDataSource(AbstractDataSource):
    """装饰 BaseDataSource：1d 全委托，1m 读 npz。"""

    def __init__(self, config, market=None):
        kwargs = {"market": market} if market is not None else {}
        self._base = BaseDataSource(config, **kwargs)
        self._min = _MinuteStore()'''
new = '''class MinuteOverlayDataSource(BaseDataSource):
    """继承 BaseDataSource：1d 全原生，1m 读 npz（v2：main.py:151 直接实例化本类）。"""

    def __init__(self, config, market=None):
        kwargs = {"market": market} if market is not None else {}
        BaseDataSource.__init__(self, config, **kwargs)
        self._min = _MinuteStore()'''
assert old in src, "old1"
src = src.replace(old, new)

src = src.replace('        return self._base.available_data_range(frequency)',
                  '        return BaseDataSource.available_data_range(self, frequency)')
src = src.replace('        return self._base.get_bar(instrument, dt, frequency)',
                  '        return BaseDataSource.get_bar(self, instrument, dt, frequency)')
src = src.replace('        return self._base.history_bars(',
                  '        return BaseDataSource.history_bars(self,')

old_ga = '''    # ---- 其余全委托 ----
    def __getattr__(self, name):
        return getattr(self._base, name)'''
assert old_ga in src, "old2"
src = src.replace(old_ga, '')

old_su = '''    def start_up(self, env, mod_config):
        self._mod_config = mod_config
        base_config = env.config.base
        market = getattr(base_config, "market", "CN")
        from rqalpha.const import MARKET as _M
        env.set_data_source(MinuteOverlayDataSource(base_config, market=_M(market)))'''
new_su = '''    def start_up(self, env, mod_config):
        # main.py:150 `if not hasattr(env, "data_source")` 在 mod_handler.start_up() 之后，
        # 换掉 main 模块引用的 BaseDataSource 名字，原生实例化点即产出本类。
        self._mod_config = mod_config
        import rqalpha.main as _m
        _m.BaseDataSource = MinuteOverlayDataSource'''
assert old_su in src, "old3"
src = src.replace(old_su, new_su)

open('rqalpha_mod_stockdb_min.py','w').write(src)
import ast; ast.parse(src); print('patch OK')
