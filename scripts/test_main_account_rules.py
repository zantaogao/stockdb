#!/usr/bin/env python3
"""主账户规则单测（2026-09-11 L1/L3/L4）

覆盖：
  L1 持仓上限 软 20 / 硬 25（2026-09-21 解闸恢复；9/11 曾收敛为 12/15）
  L3 止损梯级 -6%(尾盘确认) / -12%(加速) / -15%(硬)（原 -6/-9/-12）
  L4 tick 内行业计数累加 → 同 tick 连买同行业第 2 只被拦（原实现漏累加，实测电气设备 3 只）
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intraday_decision as I  # noqa: E402

IND = '电气设'  # get_industry 统一截断到 3 字（不是 bug，是全系统口径）


class TestPositionCaps(unittest.TestCase):
    def test_caps(self):
        self.assertEqual(I.MAX_POSITIONS, 20)
        self.assertEqual(I.HARD_MAX_POSITIONS, 25)
        self.assertLessEqual(I.MAX_POSITIONS, I.HARD_MAX_POSITIONS)

    def test_single_position_ratio(self):
        # 解闸回 20/25（2026-09-21）：单票权重由 POSITION_SCALE(5/10/15%) 决定，与只数上限解耦
        self.assertEqual(I.MAX_POSITION_RATIO, 0.20)


class TestStopLadder(unittest.TestCase):
    def test_levels(self):
        floor_pct = (I.FLOAT_STOP_FLOOR - 1) * 100   # -6%（跌破止损价下限，尾盘确认）
        self.assertAlmostEqual(floor_pct, -6.0, places=6)
        self.assertEqual(I.ACCEL_STOP, -12.0)        # 加速止损（无条件）
        self.assertEqual(I.HARD_STOP, -15.0)         # 硬止损（无条件）

    def test_ladder_order(self):
        """梯级必须逐级放宽：-6% → -12% → -15%，不能倒挂（倒挂会让紧的档先触发=白改）"""
        floor_pct = (I.FLOAT_STOP_FLOOR - 1) * 100
        self.assertGreater(floor_pct, I.ACCEL_STOP)
        self.assertGreater(I.ACCEL_STOP, I.HARD_STOP)


class TestIndustryCap(unittest.TestCase):
    def test_third_same_industry_blocked(self):
        reason = I.check_buy_conditions('600312', 90, 10.0, 0.0, {IND: 2}, 0.0)
        self.assertNotEqual(reason, 'ok')
        self.assertIn('2', reason)

    def test_tick_increment_blocks_second_buy(self):
        """L4 回归测试：同一 tick 内先买一只，计数必须累加，第二只同行业被拦"""
        counts = {IND: 1}
        self.assertEqual(I.check_buy_conditions('601727', 90, 10.0, 0.0, counts, 0.0), 'ok')
        I.bump_industry(counts, '601727')
        self.assertEqual(counts[IND], 2)
        second = I.check_buy_conditions('600312', 90, 10.0, 0.0, counts, 0.0)
        self.assertNotEqual(second, 'ok', '同 tick 第二只同行业票应被拦（L4）')

    def test_bump_uses_same_key_as_counting(self):
        """累计键必须与存量统计键同口径（3 字截断），否则计数被拆成两个 key → 上限失效"""
        counts = {}
        I.bump_industry(counts, '601727')
        self.assertEqual(list(counts.keys()), [I.get_industry('601727')])


if __name__ == '__main__':
    unittest.main(verbosity=2)
