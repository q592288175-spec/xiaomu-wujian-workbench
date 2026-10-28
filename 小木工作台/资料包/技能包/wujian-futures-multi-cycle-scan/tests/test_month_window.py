import importlib.util
import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("month_window_scan",ROOT/"scripts/scan.py")
scan=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

class MonthWindowTests(unittest.TestCase):
    def test_older_high_blocks_month_window_but_not_legacy_five(self):
        frame=pd.DataFrame({"high":[150.]*7+[120.]*5+[135.]*3,"low":[60.]*7+[80.]*5+[90.]*3})
        self.assertTrue(scan.window_break(frame,3,5)["up"])
        self.assertFalse(scan.window_break(frame,3,12)["up"])
        frame.loc[14,"high"]=155.
        self.assertTrue(scan.window_break(frame,3,12)["up"])

    def test_short_mirror_and_equal_boundary(self):
        frame=pd.DataFrame({"high":[150.]*7+[140.]*5+[135.]*3,"low":[60.]*7+[80.]*5+[70.]*3})
        self.assertTrue(scan.window_break(frame,3,5)["down"])
        self.assertFalse(scan.window_break(frame,3,12)["down"])
        frame.loc[14,"low"]=60.
        self.assertFalse(scan.window_break(frame,3,12)["down"])
        frame.loc[14,"low"]=55.
        self.assertTrue(scan.window_break(frame,3,12)["down"])

    def test_fourteen_months_is_unknown_not_a_shorter_window(self):
        frame=pd.DataFrame({"high":[100.]*14,"low":[50.]*14})
        self.assertIsNone(scan.window_break(frame,3,12))

    def test_short_month_history_does_not_remove_other_modes(self):
        days=pd.bdate_range("2025-11-03","2026-10-20")
        history=pd.DataFrame({"date":days,"open":[100.+i for i in range(len(days))],
            "high":[102.+i for i in range(len(days))],"low":[99.+i for i in range(len(days))],
            "close":[101.+i for i in range(len(days))],"volume":50000.,"open_interest":60000.})
        product={"code":"AA","name":"合成品种","exchange":"SHFE","sector":"合成"}
        config=json.loads((ROOT/"config/products.json").read_text(encoding="utf-8"))
        legacy={**config,"breakout":{**config["breakout"],"month_previous":5}}
        with patch.object(scan,"fetch_sina",side_effect=lambda *_:history.copy()):
            old=scan.analyze(product,"AA2611",legacy,date(2026,10,20))
            current=scan.analyze(product,"AA2611",config,date(2026,10,20))
        self.assertTrue(old["ok"],old)
        self.assertTrue(current["ok"],current)
        self.assertEqual(current["technical_modes"]["month-week"],scan.STATUS_INSUFFICIENT)
        self.assertFalse(current["month_break_available"])
        self.assertIn("月周大周期所需15个月",scan.mode_reason(current,"month-week"))
        for mode in ["week-day","month-week-day"]:
            self.assertEqual(current["technical_modes"][mode],old["technical_modes"][mode])
            self.assertEqual(current["modes"][mode],old["modes"][mode])
        for key in ["month_ma10","previous_month_ma10","week_ma10","day_ma10","week_higher_low","day_higher_low","volume","open_interest","liquidity_ok","main_contract","data_date"]:
            self.assertEqual(current[key],old[key],key)

if __name__=="__main__":
    unittest.main()
