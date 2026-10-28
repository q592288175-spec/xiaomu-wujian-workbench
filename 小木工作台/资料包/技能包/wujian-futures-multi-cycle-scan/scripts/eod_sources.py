"""Dated exchange closes and explicitly provisional post-close quotes."""
import csv
import json
import math
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

SHANGHAI = ZoneInfo('Asia/Shanghai')
HEADERS = {'Referer': 'https://finance.sina.com.cn/', 'User-Agent': 'Mozilla/5.0'}
EXCHANGE_NAMES = {'SHFE': '上期所', 'INE': '能源中心', 'DCE': '大商所', 'CZCE': '郑商所', 'GFEX': '广期所', 'CFFEX': '中金所'}


def valid_bar(row):
    try:
        values = {key: float(row[key]) for key in ('open', 'high', 'low', 'close', 'volume', 'open_interest')}
        if not all(math.isfinite(value) for value in values.values()):
            return None
        if min(values[key] for key in ('open', 'high', 'low', 'close')) <= 0:
            return None
        if min(values['volume'], values['open_interest']) < 0:
            return None
        if values['low'] > min(values['open'], values['close']) or values['high'] < max(values['open'], values['close']):
            return None
        if values['low'] > values['high']:
            return None
        return {**row, **values}
    except (KeyError, ValueError, TypeError):
        return None


def parse_quote(payload, contract, exchange, target, now):
    match = re.search(r'var hq_str_nf_' + re.escape(contract) + r'="([^"]*)";', payload)
    if not match or not match[1] or now.date() != target or now.time() < time(15, 30):
        return None
    fields = next(csv.reader([match[1]]))
    try:
        if exchange == 'CFFEX':
            day, stamp = fields[36], fields[37]
            row = dict(zip(('open', 'high', 'low', 'close', 'volume'), fields[:5]))
            row['open_interest'] = fields[6]
        else:
            day, stamp = fields[17], fields[1]
            row = {'open': fields[2], 'high': fields[3], 'low': fields[4], 'close': fields[8],
                   'volume': fields[14], 'open_interest': fields[13]}
        quote_time = datetime.strptime(stamp, '%H:%M:%S' if ':' in stamp else '%H%M%S').time()
        product = re.match(r'[A-Z]+', contract)[0]
        closing = time(15, 15) if product in {'T', 'TF', 'TS', 'TL'} else time(15)
        # Night-session quotes cannot be mistaken for the previous afternoon close.
        if day != target.isoformat() or not closing <= quote_time < time(16, 30) or quote_time > now.time():
            return None
        row.update(date=day, source='新浪盘后快照', provisional=True, quote_time=quote_time.isoformat())
        return valid_bar(row)
    except (IndexError, ValueError, TypeError):
        return None


def contract_key(symbol, exchange, target):
    symbol = str(symbol).upper()
    if exchange == 'CZCE':
        match = re.fullmatch(r'([A-Z]+)(\d)(\d{2})', symbol)
        if match:
            year = target.year // 10 * 10 + int(match[2])
            if year < target.year - 1:
                year += 10
            return f'{match[1]}{year % 100:02d}{match[3]}'
    return symbol


def target_day(as_of):
    from akshare.futures.cons import get_calendar
    known = sorted(str(value).replace('-', '') for value in get_calendar())
    stamp = as_of.strftime('%Y%m%d')
    if stamp > known[-1]:
        raise ValueError('交易日历未覆盖扫描日期，需更新日历')
    return datetime.strptime(max(day for day in known if day <= stamp), '%Y%m%d').date()


def collect_closes(products, mapping, target, output_dir):
    import akshare as ak
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(SHANGHAI)
    stamp = target.strftime('%Y%m%d')
    official, quotes, errors, no_trade = {}, {}, [], {}
    # Acquire the dated post-close snapshot first, before slower exchange requests.
    contracts = sorted({mapping[p['code']] for p in products if p['code'] in mapping})
    if now.date() == target and now.time() >= time(15, 30):
        for offset in range(0, len(contracts), 30):
            batch = contracts[offset:offset + 30]
            try:
                response = requests.get('https://hq.sinajs.cn/list=' + ','.join('nf_' + c for c in batch),
                                        headers=HEADERS, timeout=20)
                response.raise_for_status()
                (output_dir / f'quotes-{offset}.txt').write_text(response.text, encoding='utf-8')
                for product in products:
                    contract = mapping.get(product['code'])
                    if contract in batch:
                        row = parse_quote(response.text, contract, product['exchange'], target, now)
                        if row:
                            quotes[contract] = row
            except Exception as exc:
                errors.append({'source': '新浪盘后快照', 'error': type(exc).__name__})
    for exchange in sorted({p['exchange'] for p in products}):
        try:
            if exchange == 'CFFEX':
                frame = ak.futures_hist_daily_cffex(date=stamp)
            else:
                frame = ak.get_futures_daily(start_date=stamp, end_date=stamp, market=exchange)
            frame.to_json(output_dir / f'{exchange}.json', orient='records', force_ascii=False)
            for product in products:
                if product['exchange'] != exchange or 'variety' not in frame.columns:
                    continue
                group = frame[frame['variety'].astype(str).str.upper() == product['code']]
                if group.empty:
                    continue
                dated = group['date'].astype(str).str.replace('-', '', regex=False).str[:8].eq(stamp).all()
                inactive = all(pd.to_numeric(group[key], errors='coerce').eq(0).all() for key in ('volume', 'open_interest', 'open', 'high', 'low', 'close'))
                if dated and inactive:
                    no_trade[product['code']] = EXCHANGE_NAMES[exchange] + '日行情'
            for record in frame.to_dict('records'):
                if str(record.get('date', '')).replace('-', '')[:8] != stamp:
                    continue
                row = valid_bar({**record, 'date': target.isoformat(), 'source': EXCHANGE_NAMES[exchange] + '日行情', 'provisional': False})
                if row:
                    official[contract_key(record['symbol'], exchange, target)] = row
        except Exception as exc:
            errors.append({'source': exchange + '交易所日行情', 'error': type(exc).__name__})
    result = {**quotes, **official}
    result['_no_trade'] = no_trade
    (output_dir / 'manifest.json').write_text(json.dumps({
        'target_date': target.isoformat(), 'fetched_at': now.isoformat(),
        'contracts': result, 'errors': errors,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def merge_close(history, contract, supplement, cache_dir, as_of):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (contract + '.json')
    frames = []
    if path.exists():
        saved = pd.DataFrame(json.loads(path.read_text(encoding='utf-8')))
        saved['date'] = pd.to_datetime(saved['date'])
        frames.append(saved)
    history = history.copy()
    history['source'], history['provisional'] = '新浪历史日K', False
    frames.append(history)
    if supplement:
        fresh = pd.DataFrame([supplement])
        fresh['date'] = pd.to_datetime(fresh['date'])
        frames.append(fresh)
    merged = pd.concat(frames, ignore_index=True)
    merged['_priority'] = merged['source'].map(lambda value: 1 if value == '新浪盘后快照' else 2 if value == '新浪历史日K' else 3)
    merged = merged.sort_values(['date', '_priority'], kind='stable').drop_duplicates('date', keep='last').drop(columns='_priority')
    # Preserve later cached observations during historical queries; never feed them into calculations.
    temporary = path.with_suffix('.json.tmp')
    merged.to_json(temporary, orient='records', date_format='iso', force_ascii=False)
    temporary.replace(path)
    return merged[merged['date'].dt.date <= as_of].reset_index(drop=True)
