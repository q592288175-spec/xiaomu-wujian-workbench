import importlib.util
import json
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("multi_cycle_scan", ROOT / "scripts" / "scan.py")
scan = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(scan)


def signals(
    month="上升",
    week="上升",
    day="上升",
    week_higher_low=True,
    week_lower_high=False,
    day_higher_low=True,
    day_lower_high=False,
    month_break_up=True,
    month_break_down=False,
    month_resonance_break_available=True,
    month_resonance_break_up=None,
    month_resonance_break_down=None,
    week_break_up=True,
    week_break_down=False,
):
    if month_resonance_break_up is None:
        month_resonance_break_up = month_break_up
    if month_resonance_break_down is None:
        month_resonance_break_down = month_break_down
    return {
        "month_direction": month,
        "week_direction": week,
        "day_direction": day,
        "week_higher_low": week_higher_low,
        "week_lower_high": week_lower_high,
        "day_higher_low": day_higher_low,
        "day_lower_high": day_lower_high,
        "month_break_up": month_break_up,
        "month_break_down": month_break_down,
        "month_resonance_break_available": month_resonance_break_available,
        "month_resonance_break_up": month_resonance_break_up,
        "month_resonance_break_down": month_resonance_break_down,
        "week_break_up": week_break_up,
        "week_break_down": week_break_down,
    }


def bars(highs, lows):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(highs), freq="D"),
        "open": highs,
        "high": highs,
        "low": lows,
        "close": highs,
    })


def latest_bar(volume=50000, open_interest=50000, day="2026-09-24"):
    return pd.Series({
        "date": pd.Timestamp(day),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": volume, "open_interest": open_interest,
    })


class ClassificationTests(unittest.TestCase):
    def test_long_conditions_hit_all_three_modes(self):
        result = scan.classify_modes(signals())
        self.assertEqual(set(result.values()), {"多头观察"})

    def test_short_conditions_are_exact_mirror(self):
        result = scan.classify_modes(signals(
            month="下降", week="下降", day="下降",
            week_higher_low=False, week_lower_high=True,
            day_higher_low=False, day_lower_high=True,
            month_break_up=False, month_break_down=True,
            week_break_up=False, week_break_down=True,
        ))
        self.assertEqual(set(result.values()), {"空头观察"})

    def test_month_week_uses_week_structure_not_day_structure(self):
        result = scan.classify_modes(signals(day_higher_low=False))
        self.assertEqual(result["month-week"], "多头观察")
        self.assertEqual(result["week-day"], "未纳入")
        self.assertEqual(result["month-week-day"], "多头观察")

    def test_day_modes_use_day_structure_not_week_structure(self):
        result = scan.classify_modes(signals(week_higher_low=False))
        self.assertEqual(result["month-week"], "未纳入")
        self.assertEqual(result["week-day"], "多头观察")
        self.assertEqual(result["month-week-day"], "多头观察")

    def test_flat_ma10_is_neither_long_nor_short(self):
        result = scan.classify_modes(signals(month="走平", week="走平", day="走平"))
        self.assertEqual(set(result.values()), {"未纳入"})

    def test_classification_has_no_price_position_input(self):
        result = scan.classify_modes(signals())
        self.assertEqual(result["month-week-day"], "多头观察")

    def test_month_week_requires_month_breakout(self):
        result = scan.classify_modes(signals(month_break_up=False))
        self.assertEqual(result["month-week"], "未纳入")
        self.assertEqual(result["month-week-day"], "未纳入")

    def test_week_day_requires_week_breakout(self):
        result = scan.classify_modes(signals(week_break_up=False))
        self.assertEqual(result["week-day"], "未纳入")
        self.assertEqual(result["month-week"], "多头观察")

    def test_resonance_uses_three_months_against_previous_twelve(self):
        result = scan.classify_modes(signals(month_break_up=False, month_resonance_break_up=True,
                                             day_higher_low=False, week_break_up=False))
        self.assertEqual(result["month-week-day"], "多头观察")
        self.assertEqual(result["month-week"], "未纳入")

    def test_resonance_does_not_require_daily_structure(self):
        result = scan.classify_modes(signals(day_higher_low=False, day_lower_high=False))
        self.assertEqual(result["month-week-day"], "多头观察")

    def test_resonance_short_mirror_uses_three_months_against_previous_twelve(self):
        result = scan.classify_modes(signals(
            month="下降", week="下降", day="下降",
            week_higher_low=False, week_lower_high=True,
            day_higher_low=False, day_lower_high=True,
            month_break_up=False, month_break_down=False,
            month_resonance_break_up=False, month_resonance_break_down=True,
            week_break_up=False, week_break_down=False,
        ))
        self.assertEqual(result["month-week-day"], "空头观察")

    def test_resonance_returns_data_insufficient_without_fifteen_months(self):
        result = scan.classify_modes(signals(month_resonance_break_available=False))
        self.assertEqual(result["month-week-day"], "数据不足")


class LiquidityTests(unittest.TestCase):
    def test_equal_to_threshold_fails(self):
        ok, reason = scan.liquidity_check(latest_bar(volume=20000, open_interest=50000),
                                          date(2026, 9, 24), 20000, 20000)
        self.assertFalse(ok)
        self.assertIn("成交量", reason)

    def test_open_interest_equal_to_threshold_fails(self):
        ok, reason = scan.liquidity_check(latest_bar(volume=90000, open_interest=20000),
                                          date(2026, 9, 24), 20000, 20000)
        self.assertFalse(ok)
        self.assertIn("持仓量", reason)

    def test_both_above_threshold_pass(self):
        ok, reason = scan.liquidity_check(latest_bar(volume=20001, open_interest=20001),
                                          date(2026, 9, 24), 20000, 20000)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_missing_values_are_insufficient(self):
        ok, reason = scan.liquidity_check(latest_bar(volume=float("nan")),
                                          date(2026, 9, 24), 20000, 20000)
        self.assertFalse(ok)
        self.assertIn("缺失", reason)

    def test_date_mismatch_is_rejected(self):
        ok, reason = scan.liquidity_check(latest_bar(day="2026-09-23"),
                                          date(2026, 9, 24), 20000, 20000)
        self.assertFalse(ok)
        self.assertIn("不一致", reason)

    def test_failed_liquidity_removes_all_modes(self):
        modes = {key: "多头观察" for key in scan.MODE_LABELS}
        result = scan.apply_liquidity(modes)
        self.assertEqual(set(result.values()), {"流动性不合格"})


class BreakoutTests(unittest.TestCase):
    def test_window_uses_recent_three_against_previous_five(self):
        frame = bars(
            highs=[200, 90, 95, 92, 88, 100, 105, 108, 110],
            lows=[50, 60, 62, 61, 58, 59, 57, 55, 54],
        )
        result = scan.window_break(frame, 3, 5)
        self.assertEqual(result["previous_high"], 100.0)
        self.assertEqual(result["recent_high"], 110.0)
        self.assertTrue(result["up"])
        self.assertTrue(result["down"])

    def test_equal_extremes_are_not_breakouts(self):
        frame = bars(
            highs=[100, 95, 90, 80, 70, 99, 98, 100],
            lows=[60, 62, 61, 63, 64, 65, 66, 60],
        )
        result = scan.window_break(frame, 3, 5)
        self.assertFalse(result["up"])
        self.assertFalse(result["down"])

    def test_window_requires_eight_bars(self):
        frame = bars(highs=[1, 2, 3, 4, 5, 6, 7], lows=[1, 2, 3, 4, 5, 6, 7])
        self.assertIsNone(scan.window_break(frame, 3, 5))

    def test_resonance_window_requires_fifteen_months(self):
        frame = bars(highs=list(range(100, 115)), lows=list(range(50, 65)))
        self.assertIsNone(scan.window_break(frame.iloc[:14], 3, 12))
        result = scan.window_break(frame, 3, 12)
        self.assertEqual(result["previous_high"], 111.0)
        self.assertEqual(result["recent_high"], 114.0)
        self.assertTrue(result["up"])


class PeriodTests(unittest.TestCase):
    def test_closing_snapshot_appends_or_replaces_latest_day(self):
        frame = bars(highs=[10, 11], lows=[8, 9])
        snapshot = {
            "date": pd.Timestamp("2026-01-02"), "open": 20, "high": 22, "low": 19,
            "close": 21, "volume": 30000, "open_interest": 40000,
        }
        merged = scan.upsert_daily_bar(frame, snapshot)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged.iloc[-1].low, 19)

    def test_unfinished_week_is_excluded(self):
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2026-09-18", "2026-09-21"]),
            "open": [10, 11], "high": [12, 13], "low": [9, 10], "close": [11, 12],
        })
        weekly = scan.aggregate_bars(frame, "W-FRI", completed_only=True, as_of=date(2026, 9, 23))
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly.iloc[-1].data_date.date(), date(2026, 9, 18))

    def test_dynamic_week_includes_current_week(self):
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2026-09-18", "2026-09-21", "2026-09-22"]),
            "open": [10, 11, 10], "high": [12, 13, 11], "low": [9, 10, 8], "close": [11, 12, 9],
        })
        weekly = scan.aggregate_bars(frame, "W-FRI", completed_only=False, as_of=date(2026, 9, 23))
        self.assertEqual(len(weekly), 2)
        self.assertEqual(weekly.iloc[-1].low, 8)
        self.assertLessEqual(weekly.iloc[-1].low, weekly.iloc[-2].low)

    def test_daily_long_requires_yesterday_higher_low_and_today_protection(self):
        frame = bars(highs=[110, 111, 112], lows=[100, 105, 105])
        result = scan.day_structure(frame)
        self.assertTrue(result["higher_low"])
        self.assertFalse(result["lower_high"])

    def test_daily_long_fails_when_today_breaks_yesterday_low(self):
        frame = bars(highs=[110, 111, 112], lows=[100, 105, 104])
        self.assertFalse(scan.day_structure(frame)["higher_low"])

    def test_daily_short_requires_yesterday_lower_high_and_today_protection(self):
        frame = bars(highs=[110, 105, 105], lows=[100, 99, 98])
        result = scan.day_structure(frame)
        self.assertTrue(result["lower_high"])
        self.assertFalse(result["higher_low"])

    def test_direction_equality_is_flat(self):
        self.assertEqual(scan.direction(10.0, 10.0), "走平")


class ConfigurationTests(unittest.TestCase):
    def test_universe_contains_87_unique_products(self):
        config = json.loads((ROOT / "config" / "products.json").read_text(encoding="utf-8"))
        codes = [product["code"] for product in config["products"]]
        self.assertEqual(len(codes), 87)
        self.assertEqual(len(set(codes)), 87)

    def test_every_product_has_a_known_sector(self):
        config = json.loads((ROOT / "config" / "products.json").read_text(encoding="utf-8"))
        known = set(config["sector_order"])
        self.assertTrue(all(product["sector"] in known for product in config["products"]))

    def test_liquidity_threshold_is_20000(self):
        config = json.loads((ROOT / "config" / "products.json").read_text(encoding="utf-8"))
        self.assertEqual(config["liquidity"]["volume_min"], 20000)
        self.assertEqual(config["liquidity"]["open_interest_min"], 20000)
        self.assertTrue(config["liquidity"]["strict_greater_than"])

    def test_month_window_is_three_against_twelve_and_week_stays_five(self):
        config = json.loads((ROOT / "config" / "products.json").read_text(encoding="utf-8"))
        self.assertEqual(config["breakout"]["month_recent"], 3)
        self.assertEqual(config["breakout"]["month_previous"], 12)
        self.assertEqual(config["breakout"]["week_recent"], 3)
        self.assertEqual(config["breakout"]["week_previous"], 5)

    def test_resonance_window_is_three_against_twelve(self):
        config = json.loads((ROOT / "config" / "products.json").read_text(encoding="utf-8"))
        self.assertEqual(config["breakout"]["resonance_month_recent"], 3)
        self.assertEqual(config["breakout"]["resonance_month_previous"], 12)


if __name__ == "__main__":
    unittest.main()
