"""合成行情只验证规则与兼容性，不用于声称真实表现。"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attention
import scan


def frame(closes, highs=None, lows=None, freq="B", start="2026-09-01"):
    result = pd.DataFrame({
        "date": pd.date_range(start, periods=len(closes), freq=freq), "open": closes, "close": closes,
        "high": highs if highs is not None else [v + 0.4 for v in closes],
        "low": lows if lows is not None else [v - 0.4 for v in closes],
        "volume": 50000, "open_interest": 60000,
    })
    return result


def monthly_sample():
    result = pd.DataFrame({"high": [100.] * 12 + [100., 120., 118.], "low": [50.] * 15,
                           "close": [75.] * 12 + [110., 112., 108.], "open": [75.] * 15},
                          index=pd.period_range("2025-07", periods=15, freq="M"))
    return result


def monthly_breakout_sample():
    return pd.DataFrame({"high": [100.] * 10 + [120., 115.], "low": [50.] * 12,
                         "close": [75.] * 10 + [110., 108.], "open": [75.] * 12},
                        index=pd.period_range("2025-10", periods=12, freq="M"))


def event_history():
    return frame([110.], highs=[120.], lows=[105.], start="2026-08-03")


def compact_frame(close=108., low=None):
    values = [80., 82., 85., 90., 97., 103., 105., 104., 105., 104., close]
    result = frame(values)
    if low is not None:
        result.loc[result.index[-1], "low"] = low
    return result


def mirror(data):
    result = data.copy()
    result["high"], result["low"] = 200 - data.low, 200 - data.high
    result["close"] = 200 - data.close
    result["open"] = 200 - data.open
    return result


def row(qualified=True):
    return {
        "month_direction": "上升", "week_direction": "上升", "day_direction": "上升",
        "month_break_up": True, "month_break_down": False, "week_break_up": False, "week_break_down": False,
        "month_resonance_break_available": True, "month_resonance_break_up": True,
        "month_resonance_break_down": False,
        "liquidity_ok": True, "liquidity_reason": "",
        "modes": {"month-week": "多头观察", "week-day": "未纳入",
                  "month-week-day": "多头观察" if qualified else "未纳入"},
    }


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.rule = attention.settings({})

    def test_high_location_with_missing_eighteen_months(self):
        result = attention.positions(monthly_sample(), 108, self.rule)
        self.assertEqual(result["12"]["location"], "高位")
        self.assertFalse(result["18"]["available"])

    def test_bottom_rebound_can_make_eight_month_high_without_high_long_position(self):
        monthly = monthly_sample()
        monthly.iloc[:4, monthly.columns.get_loc("high")] = 200
        result = attention.positions(monthly, 108, self.rule)
        self.assertTrue(result["8"]["recent_three_new_high"])
        self.assertEqual(result["12"]["location"], "区间中部")

    def test_boundaries_include_exact_upper_lower_quarters(self):
        monthly = monthly_sample()
        self.assertEqual(attention.positions(monthly, 102.5, self.rule)["12"]["location"], "高位")
        self.assertEqual(attention.positions(monthly, 67.5, self.rule)["12"]["location"], "低位")

    def test_short_position_is_exact_mirror(self):
        long = attention.positions(monthly_sample(), 108, self.rule)["12"]
        short = attention.positions(mirror(monthly_sample()), 92, self.rule)["12"]
        self.assertAlmostEqual(long["position_pct"] + short["position_pct"], 100)
        self.assertEqual(short["location"], "低位")

    def test_zero_width_missing_month_and_nan_are_not_fabricated(self):
        monthly = monthly_sample()
        monthly[["high", "low"]] = 100
        self.assertFalse(attention.positions(monthly, 100, self.rule)["12"]["available"])
        missing = pd.concat([monthly_sample().iloc[:6], monthly_sample().iloc[7:]])
        missing.loc[pd.Period("2025-08", "M")] = monthly_sample().iloc[0]
        missing = missing.sort_index()
        self.assertFalse(attention.positions(missing, 108, self.rule)["12"]["available"])
        monthly = monthly_sample()
        monthly.iloc[-1, monthly.columns.get_loc("high")] = float("nan")
        self.assertFalse(attention.positions(monthly, 108, self.rule)["12"]["available"])

    def test_bad_settings_rejected(self):
        for changes in ({"position_edge": 0.5}, {"state_lookback": 4}, {"position_months": 12.5}):
            with self.assertRaises(ValueError):
                attention.settings({"attention": changes})


class BoundaryTests(unittest.TestCase):
    def context(self, closes):
        daily = frame(closes, start="2026-09-28")
        return attention.breakout_context(monthly_breakout_sample(), event_history(), daily, "多头观察")

    def test_held_boundary_records_original_period_and_first_touch(self):
        result = self.context([109, 108])
        self.assertEqual(result["status"], "突破保持")
        self.assertEqual(result["boundary"], 100)
        self.assertEqual(result["event_period"], "2026-08")
        self.assertEqual(result["event_date"], "2026-08-03")
        self.assertEqual(result["reference_start"], "2026-03")

    def test_two_closes_inside_fail_one_close_or_equal_only_waits(self):
        self.assertEqual(self.context([99, 98])["status"], "突破失守")
        self.assertEqual(self.context([108, 98])["status"], "回踩待确认")
        self.assertEqual(self.context([99, 100])["status"], "回踩待确认")

    def test_intraday_wick_does_not_destroy_held_close(self):
        daily = frame([108, 107], lows=[90, 90], start="2026-09-28")
        result = attention.breakout_context(monthly_breakout_sample(), event_history(), daily, "多头观察")
        self.assertEqual(result["status"], "突破保持")

    def test_do_not_count_pre_event_close_as_second_failure(self):
        monthly = monthly_breakout_sample()
        monthly.loc[pd.Period("2026-08", "M"), "high"] = 100
        latest = frame([95, 95], highs=[99, 115], start="2026-09-29")
        result = attention.breakout_context(monthly, latest, latest, "多头观察")
        self.assertEqual(result["event_date"], "2026-09-30")
        self.assertEqual(result["status"], "回踩待确认")

    def test_rolling_high_expiry_does_not_invent_new_breakout_event(self):
        monthly = monthly_breakout_sample()
        monthly.high = [100, 100, 100, 150, 100, 100, 100, 100, 100, 110, 105, 101]
        self.assertTrue(scan.window_break(monthly, 3, 5)["up"])
        result = attention.breakout_context(monthly, event_history(), frame([108]), "多头观察")
        self.assertFalse(result["available"])

    def test_boundary_does_not_roll_with_new_month_without_new_event(self):
        monthly = monthly_breakout_sample()
        before = self.context([108])
        monthly.loc[pd.Period("2026-10", "M")] = [112, 50, 108, 108]
        after = attention.breakout_context(monthly, event_history(), frame([108], start="2026-10-09"), "多头观察")
        self.assertEqual(before["boundary"], after["boundary"])
        self.assertEqual(before["reference_start"], after["reference_start"])

    def test_short_breakout_and_failure_are_exact_mirrors(self):
        for closes in ([109, 108], [99, 98], [108, 98]):
            daily = frame(closes, start="2026-09-28")
            long = attention.breakout_context(monthly_breakout_sample(), event_history(), daily, "多头观察")
            short = attention.breakout_context(mirror(monthly_breakout_sample()), mirror(event_history()), mirror(daily), "空头观察")
            self.assertEqual(long["status"], short["status"])
            self.assertAlmostEqual(long["boundary"] + short["boundary"], 200)


class StateTests(unittest.TestCase):
    rule = attention.settings({})

    def test_close_breakout_after_compact_base(self):
        result = attention.pattern_state(compact_frame(), "多头观察", self.rule)
        self.assertEqual(result["state"], "蓄力后上破")
        self.assertLessEqual(result["box_ratio"], self.rule["consolidation_ratio_max"])

    def test_tight_consolidation_is_waiting_not_failure(self):
        result = attention.pattern_state(compact_frame(close=104.5), "多头观察", self.rule)
        self.assertEqual(result["state"], "高位整理")

    def test_wick_breakout_or_equal_close_is_not_breakout(self):
        for close in (104.5, 105.4):
            sample = compact_frame(close=close)
            sample.loc[sample.index[-1], "high"] = 150
            result = attention.pattern_state(sample, "多头观察", self.rule)
            self.assertEqual(result["state"], "上破未站稳")

    def test_lower_wick_recovery_is_not_short_consolidation(self):
        sample = mirror(compact_frame(close=104.5))
        sample.loc[sample.index[-1], "low"] = 10
        self.assertEqual(attention.pattern_state(sample, "空头观察", self.rule)["state"], "下破未站稳")

    def test_reverse_side_violation_not_called_healthy_consolidation(self):
        result = attention.pattern_state(compact_frame(close=104.5, low=100), "多头观察", self.rule)
        self.assertEqual(result["state"], "回撤待确认")

    def test_sustained_progress_and_single_jump_are_distinguished(self):
        self.assertEqual(attention.pattern_state(frame(list(range(100, 111))), "多头观察", self.rule)["state"], "持续清晰推进")
        self.assertEqual(attention.pattern_state(frame([100] * 10 + [150]), "多头观察", self.rule)["state"], "推进放缓/反复")

    def test_latest_pullback_not_labelled_current_forward_progress(self):
        result = attention.pattern_state(frame(list(range(100, 110)) + [108]), "多头观察", self.rule)
        self.assertEqual(result["state"], "推进放缓/反复")

    def test_box_excludes_current_bar(self):
        sample = compact_frame()
        base = attention.pattern_state(sample, "多头观察", self.rule)
        sample.loc[sample.index[-1], "high"] = 300
        sample.loc[sample.index[-1], "low"] = 1
        changed = attention.pattern_state(sample, "多头观察", self.rule)
        self.assertEqual(base["box_high"], changed["box_high"])
        self.assertEqual(base["box_ratio"], changed["box_ratio"])

    def test_short_states_are_exact_mirrors(self):
        for close, expected in ((108, "蓄力后下破"), (104.5, "低位整理")):
            self.assertEqual(attention.pattern_state(mirror(compact_frame(close=close)), "空头观察", self.rule)["state"], expected)

    def test_invalid_prices_do_not_produce_nan_metrics(self):
        sample = compact_frame()
        sample.loc[sample.index[-1], "high"] = float("inf")
        self.assertFalse(attention.pattern_state(sample, "多头观察", self.rule)["available"])


class AttentionLayerTests(unittest.TestCase):
    def evaluate(self, source=None, daily=None, monthly=None):
        daily = compact_frame() if daily is None else daily
        return attention.evaluate(row() if source is None else source,
                                  monthly_sample() if monthly is None else monthly,
                                  daily, pd.DataFrame(), daily, event_history(), {})

    def test_qualified_high_breakout_is_focus_without_eighteen_months(self):
        result = self.evaluate()["attention"]["month-week-day"]
        self.assertEqual(result["tier"], "重点关注")
        self.assertTrue(result["baseline_qualified"])

    def test_old_qualification_not_changed_by_new_location_rejection(self):
        source = row()
        monthly = monthly_sample()
        monthly.iloc[:4, monthly.columns.get_loc("high")] = 200
        result = self.evaluate(source=source, monthly=monthly)
        self.assertEqual(result["attention"]["month-week-day"]["state"], "长期位置不合适")
        self.assertEqual(source["modes"]["month-week-day"], "多头观察")

    def test_consolidation_can_wait_without_forging_baseline_qualification(self):
        result = self.evaluate(source=row(False), daily=compact_frame(close=104.5))["attention"]["month-week-day"]
        self.assertEqual(result["tier"], "蓄力观察")
        self.assertFalse(result["baseline_qualified"])

    def test_breakout_without_original_structure_cannot_be_focus(self):
        result = self.evaluate(source=row(False))["attention"]["month-week-day"]
        self.assertEqual(result["tier"], "暂缓关注")

    def test_week_day_against_month_not_promoted(self):
        source = row()
        source.update(month_direction="下降", week_break_up=True)
        source["modes"]["week-day"] = "多头观察"
        result = self.evaluate(source=source)["attention"]["week-day"]
        self.assertEqual(result["state"], "月线方向不一致")
        self.assertTrue(result["baseline_qualified"])

    def test_low_liquidity_never_rescued(self):
        source = row()
        source.update(liquidity_ok=False, liquidity_reason="成交量等于2万手")
        source["modes"] = scan.apply_liquidity(source["modes"])
        result = self.evaluate(source=source)
        self.assertTrue(all(item["tier"] == "未纳入" for item in result["attention"].values()))

    def test_full_short_layer_mirrors_long_layer(self):
        source = row()
        for key in ("month_direction", "week_direction", "day_direction"):
            source[key] = "下降"
        source.update(month_break_up=False, month_break_down=True,
                      month_resonance_break_up=False, month_resonance_break_down=True)
        source["modes"] = {key: value.replace("多头", "空头") for key, value in source["modes"].items()}
        daily = mirror(compact_frame())
        short = attention.evaluate(source, mirror(monthly_sample()), daily, pd.DataFrame(), daily, mirror(event_history()), {})
        long = self.evaluate()
        for mode in attention.MODE_LABELS:
            self.assertEqual(short["attention"][mode]["tier"], long["attention"][mode]["tier"])


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/products.json").read_text(encoding="utf-8"))
        cls.product = cls.config["products"][0]
        dates = pd.bdate_range(end="2026-09-30", periods=600)
        cls.daily = frame([100 + index * 0.1 for index in range(600)])
        cls.daily.date = dates
        cls.as_of = date(2026, 9, 30)

    def analyze(self, data=None):
        with patch.object(scan, "fetch_sina", return_value=self.daily.copy() if data is None else data):
            return scan.analyze(self.product, "AU2612", self.config, self.as_of)

    def test_analyze_adds_layer_but_keeps_exact_baseline_and_shared_fetch(self):
        with patch.object(scan, "fetch_sina", return_value=self.daily.copy()) as fetch:
            result = scan.analyze(self.product, "AU2612", self.config, self.as_of)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["modes"], scan.classify_modes(result))
        self.assertIn("attention", result)
        self.assertEqual(fetch.call_count, 2)

    def test_future_bars_cannot_change_current_attention(self):
        before = self.analyze()
        future = self.daily.iloc[-1:].copy()
        future.date = pd.to_datetime(["2026-10-09"])
        future[["high", "low", "close", "open"]] = 99999
        after = self.analyze(pd.concat([self.daily, future], ignore_index=True))
        self.assertEqual(before["modes"], after["modes"])
        self.assertEqual(before["attention"], after["attention"])
        self.assertEqual(before["long_term_position"], after["long_term_position"])

    def test_new_layer_failure_retains_baseline_and_reports_reason(self):
        with patch.object(attention, "evaluate", side_effect=ValueError("测试异常")):
            result = self.analyze()
        self.assertTrue(result["ok"])
        self.assertEqual(result["modes"], scan.classify_modes(result))
        self.assertEqual(result["attention"]["month-week-day"]["tier"], "数据待核")

    def test_report_and_json_have_counts_and_only_selected_mode_on_front_page(self):
        result = self.analyze()
        report, summary = scan.build_report([result], self.config, self.as_of, "month-week-day")
        self.assertIn("原始模式资格：月周日共振", report)
        self.assertEqual(summary["rule_version"], "v2.5.1")
        self.assertEqual(summary["baseline_rule_version"], "v2.5.1")
        self.assertEqual(set(summary["attention_counts"]), {"month-week-day"})
        self.assertEqual(sum(summary["attention_counts"]["month-week-day"].values()), 1)
        json.dumps(summary, ensure_ascii=False, allow_nan=False)

    def test_short_report_omits_downgrade_details_but_full_report_keeps_them(self):
        result = self.analyze()
        result["attention"]["month-week-day"].update(tier="暂缓关注", state="长期位置不合适")
        short = attention.report_lines([result], ["month-week-day"], self.config["sector_order"], tiers=("重点关注", "蓄力观察"))
        full = attention.report_lines([result], ["month-week-day"], self.config["sector_order"])
        self.assertNotIn("长期位置不合适", "\n".join(short))
        self.assertIn("长期位置不合适", "\n".join(full))


if __name__ == "__main__":
    unittest.main()
