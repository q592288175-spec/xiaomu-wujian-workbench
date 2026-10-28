import importlib.util
import unittest
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

spec = importlib.util.spec_from_file_location('eod_sources', Path(__file__).resolve().parents[1] / 'scripts/eod_sources.py')
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class ClosingTests(unittest.TestCase):
    now = datetime(2026, 9, 29, 15, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
    day = date(2026, 9, 29)

    def quote(self, stamp='150000', day='2026-09-29', contract='J2701'):
        fields = ['焦炭2701', stamp, '1956', '1974', '1925.5', '1942.5', '1942.5', '1943', '1942.5', '1947.5', '1940.5', '4', '6', '48921', '23570', '连', '焦炭', day]
        return 'var hq_str_nf_' + contract + '="' + ','.join(fields) + '";'

    def test_dated_close_is_explicitly_provisional(self):
        row = source.parse_quote(self.quote(), 'J2701', 'DCE', self.day, self.now)
        self.assertEqual(row['close'], 1942.5)
        self.assertEqual(row['low'], 1925.5)
        self.assertTrue(row['provisional'])

    def test_old_day_intraday_and_night_quotes_are_rejected(self):
        for payload in [self.quote(day='2026-09-28'), self.quote(stamp='145959'), self.quote(stamp='210000')]:
            self.assertIsNone(source.parse_quote(payload, 'J2701', 'DCE', self.day, self.now))

    def test_contract_identity_is_not_inferred_from_response_order(self):
        self.assertIsNone(source.parse_quote(self.quote(), 'JM2701', 'DCE', self.day, self.now))

    def test_treasury_waits_until_1515(self):
        fields = ['109.5', '110', '109', '109.8', '50000', '0', '60000'] + ['0'] * 29 + ['2026-09-29', '15:14:59']
        payload = 'var hq_str_nf_T2612="' + ','.join(fields) + '";'
        self.assertIsNone(source.parse_quote(payload, 'T2612', 'CFFEX', self.day, self.now))
        row = source.parse_quote(payload.replace('15:14:59', '15:15:00'), 'T2612', 'CFFEX', self.day, self.now)
        self.assertEqual(row['close'], 109.8)

    def test_ohlc_and_missing_interest_are_rejected(self):
        row = {'open': 100, 'high': 110, 'low': 90, 'close': 120, 'volume': 1, 'open_interest': 1}
        self.assertIsNone(source.valid_bar(row))
        row.update(close=100, open_interest=float('nan'))
        self.assertIsNone(source.valid_bar(row))

    def test_zhengzhou_contract_expands_using_trade_year(self):
        self.assertEqual(source.contract_key('SF611', 'CZCE', self.day), 'SF2611')
        self.assertEqual(source.contract_key('SF701', 'CZCE', self.day), 'SF2701')

    def test_weekend_target_uses_exchange_calendar(self):
        self.assertEqual(source.target_day(date(2026, 9, 20)), date(2026, 9, 18))


class CacheTests(unittest.TestCase):
    def test_cached_official_close_survives_provisional_retry_and_restart(self):
        history = pd.DataFrame([{'date': pd.Timestamp('2026-09-28'), 'open': 100, 'high': 110, 'low': 90,
                                 'close': 101, 'volume': 30000, 'open_interest': 40000}])
        official = {'date': '2026-09-29', 'open': 100, 'high': 110, 'low': 90, 'close': 105,
                    'volume': 35000, 'open_interest': 41000, 'source': '郑商所日行情', 'provisional': False}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            source.merge_close(history, 'SF2611', official, folder, date(2026, 9, 29))
            retry = source.merge_close(history, 'SF2611', {**official, 'close': 106, 'source': '新浪盘后快照', 'provisional': True}, folder, date(2026, 9, 29))
            self.assertEqual(len(retry), 2)
            self.assertEqual(retry.iloc[-1]['close'], 105)
            self.assertFalse(retry.iloc[-1]['provisional'])
            past = source.merge_close(history, 'SF2611', None, folder, date(2026, 9, 28))
            self.assertEqual(len(past), 1)
            reopened = source.merge_close(history, 'SF2611', None, folder, date(2026, 9, 29))
            self.assertEqual(reopened.iloc[-1]['close'], 105)


if __name__ == '__main__':
    unittest.main()
