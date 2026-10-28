"""Read-only quote event stream. Credentials arrive through stdin, never argv or logs."""
import sys
import json
import math
import time
import threading
import queue
from pathlib import Path
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.runtime' / 'monitor-deps'))
commands = queue.Queue()


def emit(kind, **payload):
    print(json.dumps(dict(type=kind, **payload), ensure_ascii=False, allow_nan=False), flush=True)


def stdin_reader():
    for line in sys.stdin:
        try:
            commands.put(json.loads(line))
        except (ValueError, TypeError):
            pass


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def provider_symbol(symbol):
    exchange, contract = symbol.upper().split('.')
    if exchange == 'CZCE' and len(contract.rstrip('0123456789'))+4 == len(contract):
        contract = contract.rstrip('0123456789')+contract[-3:]
    return exchange + '.' + (contract if exchange in ('CZCE', 'CFFEX') else contract.lower())


def seconds(value):
    hour, minute, second = map(int, value.split(':'))
    return hour * 3600 + minute * 60 + second


def session_info(now, trading_time, dates):
    today = now.date()
    value = now.hour * 3600 + now.minute * 60 + now.second
    if today.isoformat() in dates:
        for start, end in trading_time.get('day', []):
            if seconds(start) <= value < seconds(end):
                return dict(sessionActive=True, sessionKey=today.isoformat() + ':day:' + start, tradingDay=today.isoformat())
    base = today - timedelta(days=1) if value < 6 * 3600 else today
    night_value = value + (86400 if base != today else 0)
    if base.isoformat() in dates:
        next_day = next((date for date in dates if date > base.isoformat()), None)
        # Friday night belongs to Monday; holiday eves have no night session.
        distance = (datetime.fromisoformat(next_day).date()-base).days if next_day else 0
        allowed = distance == 1 or (base.weekday() == 4 and distance == 3)
        for start, end in trading_time.get('night', []):
            if allowed and seconds(start) <= night_value < seconds(end):
                return dict(sessionActive=True, sessionKey=base.isoformat() + ':night:' + start, tradingDay=next_day)
    return dict(sessionActive=False, sessionKey=None, tradingDay=None)


def run(config):
    try:
        from tqsdk import TqApi, TqAuth, TqSim
    except ImportError:
        emit('status', status='runtime-missing', message='实时行情运行库尚未安装')
        return
    auth = TqAuth(config['user'], config['password'])
    delay = 1
    while True:
        api = None
        try:
            emit('status', status='connecting', message='正在核验免费行情权限')
            api = TqApi(TqSim(), auth=auth, debug=False, disable_print=True)
            quote_objects, requested, expired, unavailable = {}, set(config.get('symbols', [])), set(), set()
            valid_symbols = set(api.query_quotes(ins_class='FUTURE', expired=False))
            today = datetime.now(SHANGHAI).date()
            calendar = api.get_trading_calendar(today-timedelta(days=10), today+timedelta(days=40))
            dates = sorted(row['date'].date().isoformat() for _, row in calendar.iterrows() if row['trading'])
            if not dates:
                raise ValueError('calendar')
            main_symbols = [symbol for symbol in api.query_cont_quotes() if symbol.split('.')[0] in ('SHFE', 'INE', 'DCE', 'CZCE', 'GFEX', 'CFFEX')]
            main_quotes = {symbol: api.get_quote(symbol) for symbol in main_symbols}
            main_cont = {symbol: api.get_quote('KQ.m@' + symbol.rstrip('0123456789')) for symbol in main_symbols}
            catalog_signature, sequence, last_heartbeat, last_catalog = '', 0, 0, 0
            emit('status', status='connected', message='免费期货行情连接已建立', calendarDays=len(dates), entitlementExpiry=str(auth.expire_datetime))
            while True:
                while not commands.empty():
                    command = commands.get_nowait()
                    if command.get('type') == 'stop':
                        return
                    if command.get('type') == 'subscribe':
                        requested = set(command.get('symbols', []))
                for symbol in requested:
                    if symbol not in quote_objects:
                        if provider_symbol(symbol) not in valid_symbols:
                            if symbol not in unavailable:
                                unavailable.add(symbol)
                                emit('contract-status', symbol=symbol, status='unavailable')
                            continue
                        quote_objects[symbol] = api.get_quote(provider_symbol(symbol))
                api.wait_update(deadline=time.time()+1)
                now = datetime.now(SHANGHAI)
                if now.date() != today:
                    today = now.date()
                    calendar = api.get_trading_calendar(today-timedelta(days=10), today+timedelta(days=40))
                    dates = sorted(row['date'].date().isoformat() for _, row in calendar.iterrows() if row['trading'])
                    valid_symbols = set(api.query_quotes(ins_class='FUTURE', expired=False))
                if time.monotonic()-last_catalog >= 5:
                    last_catalog = time.monotonic()
                    members = []
                    for original, initial in main_quotes.items():
                        actual = main_cont[original].underlying_symbol or original
                        q = api.get_quote(actual)
                        if not q.instrument_name:
                            continue
                        expiry = number(q.expire_datetime)
                        members.append(dict(symbol=actual.upper(), name=q.instrument_name, exchange=actual.split('.')[0], tickSize=number(q.price_tick), expiresAt=datetime.fromtimestamp(expiry, SHANGHAI).isoformat() if expiry and expiry > 0 else None))
                    signature = json.dumps(members, sort_keys=True)
                    if members and signature != catalog_signature:
                        emit('catalog', items=members, verifiedAt=now.isoformat())
                        catalog_signature = signature
                active = 0
                for symbol, q in quote_objects.items():
                    if symbol not in requested:
                        continue
                    if q.expired:
                        if symbol not in expired:
                            expired.add(symbol)
                            emit('contract-status', symbol=symbol, status='expired')
                        continue
                    info = session_info(now, {'day': q.trading_time.day, 'night': q.trading_time.night}, dates)
                    active += int(info['sessionActive'])
                    if not api.is_changing(q) or not q.datetime or q.expired:
                        continue
                    price = number(q.last_price)
                    if price is None:
                        continue
                    sequence += 1
                    quote_at = datetime.fromisoformat(q.datetime).replace(tzinfo=SHANGHAI).isoformat()
                    emit('quote', symbol=symbol, last=price, quoteAt=quote_at, receivedAt=now.isoformat(), sequence=sequence, source='TqSdk', **info)
                if time.monotonic()-last_heartbeat >= 5:
                    emit('heartbeat', at=now.isoformat(), activeContracts=active, subscribed=len(requested))
                    last_heartbeat = time.monotonic()
                delay = 1
        except (KeyboardInterrupt, BrokenPipeError):
            return
        except Exception as error:
            message = str(error)
            denied = any(word in message for word in ('认证失败', '权限', '到期', '用户名', '密码', 'auth', 'permission', 'expired'))
            emit('status', status='permission-denied' if denied else 'disconnected', message='行情认证或权限未通过，请核对免费账号' if denied else '行情连接中断，正在重连')
            if denied:
                return
            time.sleep(delay)
            delay = min(delay*2, 30)
        finally:
            if api:
                api.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
    try:
        initial = json.loads(sys.stdin.readline())
        if not initial.get('user') or not initial.get('password'):
            emit('status', status='unconfigured', message='请配置免费行情账号')
        else:
            threading.Thread(target=stdin_reader, daemon=True).start()
            run(initial)
    except Exception:
        emit('status', status='failed', message='行情采集器无法启动，请核对运行环境')
