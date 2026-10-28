import importlib.util
from pathlib import Path
from datetime import datetime
import unittest

spec = importlib.util.spec_from_file_location('monitor_market', Path(__file__).parents[1] / 'integrations' / 'monitor_market.py')
market = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market)

class SessionTests(unittest.TestCase):
    times = {'day': [['09:00:00', '10:15:00'], ['10:30:00', '11:30:00'], ['13:30:00', '15:00:00']], 'night': [['21:00:00', '26:30:00']]}
    dates = ['2026-09-30', '2026-10-09', '2026-10-12', '2026-10-13']

    def check(self, value):
        return market.session_info(datetime.fromisoformat(value), self.times, self.dates)

    def test_day_and_breaks(self):
        self.assertTrue(self.check('2026-10-12T09:00:00')['sessionActive'])
        for value in ['2026-10-12T10:20:00', '2026-10-12T12:00:00', '2026-10-12T15:00:00', '2026-10-10T09:00:00']:
            self.assertFalse(self.check(value)['sessionActive'])

    def test_friday_and_midnight(self):
        for value in ['2026-10-09T21:30:00', '2026-10-10T01:00:00']:
            result = self.check(value)
            self.assertTrue(result['sessionActive'])
            self.assertEqual(result['tradingDay'], '2026-10-12')
        self.assertFalse(self.check('2026-10-10T02:30:00')['sessionActive'])
        self.assertFalse(self.check('2026-10-11T21:00:00')['sessionActive'])

    def test_holiday_eve_and_contract_case(self):
        self.assertFalse(self.check('2026-09-30T21:00:00')['sessionActive'])
        self.assertEqual(market.provider_symbol('SHFE.CU2611'), 'SHFE.cu2611')
        self.assertEqual(market.provider_symbol('CZCE.MA701'), 'CZCE.MA701')
        self.assertEqual(market.provider_symbol('CZCE.MA2701'), 'CZCE.MA701')

if __name__ == '__main__':
    unittest.main()
