#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五简国内期货87品种多周期环境扫描 v2.5.1。

判定链：流动性双2万手硬门 -> 月/周/日MA10方向 -> 模式对应结构与突破窗口。
只筛选观察环境，不产生入场、止损、仓位或下单指令。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eod_sources import collect_closes, merge_close, target_day
import attention

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "products.json"
SINA_HOSTS = ("https://stock2.finance.sina.com.cn", "https://stock.finance.sina.com.cn")
SINA_PATH = "/futures/api/jsonp.php/var%20_{sym}=/InnerFuturesNewService.getDailyKline?symbol={sym}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

MODE_LABELS = {
    "month-week": "月周大周期",
    "week-day": "周日小周期",
    "month-week-day": "月周日共振",
}
SIDES = ("多头观察", "空头观察")
STATUS_EXCLUDED = "未纳入"
STATUS_ILLIQUID = "流动性不合格"
STATUS_INSUFFICIENT = "数据不足"

DEFAULT_VOLUME_MIN = 20_000
DEFAULT_OI_MIN = 20_000
DEFAULT_BREAKOUT = {
    "month_recent": 3,
    "month_previous": 12,
    "week_recent": 3,
    "week_previous": 5,
    "resonance_month_recent": 3,
    "resonance_month_previous": 12,
}


# ---------------------------------------------------------------- 数据读取

def resolve_as_of(value: str | None = None) -> date:
    """未指定截点时，取当前可用的最后完成交易日。"""
    if value:
        return pd.Timestamp(value).date()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.weekday() < 5 and now.time() < dtime(15, 30):
        return (now - timedelta(days=1)).date()
    return now.date()


def fetch_sina(code: str, retries: int = 4) -> pd.DataFrame:
    """读取新浪期货日K，含成交量与持仓量。"""
    symbol = code if any(character.isdigit() for character in code) else f"{code}0"
    path = SINA_PATH.format(sym=symbol)
    last_error: Exception | None = None
    for attempt in range(retries):
        for host in SINA_HOSTS:
            try:
                response = requests.get(host + path, timeout=20, headers=HEADERS)
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code} @ {host}")
                payload = response.text
                raw = json.loads(payload[payload.index("["):payload.rindex("]") + 1])
                if not raw:
                    raise ValueError("新浪行情返回空数据")
                frame = pd.DataFrame(raw).rename(columns={
                    "d": "date", "o": "open", "h": "high", "l": "low", "c": "close",
                    "v": "volume", "p": "open_interest",
                })
                for column in ("open", "high", "low", "close", "volume", "open_interest"):
                    if column not in frame.columns:
                        frame[column] = float("nan")
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
                frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
                return (frame.dropna(subset=["date", "open", "high", "low", "close"])
                             .sort_values("date").drop_duplicates("date").reset_index(drop=True))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        time.sleep(0.4 * (attempt + 1))
    raise last_error or RuntimeError("行情读取失败")


def resolve_main_contracts(config: dict, retries: int = 3) -> dict[str, str]:
    """读取当前具体主力合约，并合并人工补充映射。"""
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少akshare，无法核对当前具体主力合约") from exc

    mapping: dict[str, str] = {}
    for exchange in ("shfe", "dce", "czce", "cffex", "gfex"):
        contracts = ""
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    contracts = ak.match_main_contract(exchange)
                if contracts.strip():
                    break
                raise ValueError("AkShare主力合约映射返回空数据")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
        if not contracts.strip():
            raise last_error or RuntimeError(f"{exchange}主力合约映射失败")
        for contract in contracts.split(","):
            matched = re.match(r"([A-Za-z]+)", contract)
            if matched:
                mapping[matched.group(1).upper()] = contract.upper()
    mapping.update({key.upper(): value.upper() for key, value in config.get("main_contract_overrides", {}).items()})
    return mapping




def upsert_daily_bar(frame: pd.DataFrame, snapshot: dict | None) -> pd.DataFrame:
    if not snapshot:
        return frame
    return (pd.concat([frame, pd.DataFrame([snapshot])], ignore_index=True)
              .sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True))


# ---------------------------------------------------------------- 指标计算

def aggregate_bars(daily: pd.DataFrame, frequency: str, completed_only: bool, as_of: date) -> pd.DataFrame:
    """按周期聚合K线；completed_only=True 时只保留已完成周期。"""
    work = daily.copy()
    work["period"] = work["date"].dt.to_period(frequency)
    grouped = work.groupby("period", sort=True)
    bars = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    bars["data_date"] = grouped["date"].last()
    bars["period_end"] = bars.index.end_time.normalize()
    if completed_only:
        bars = bars[bars["period_end"].dt.date <= as_of]
    bars["ma10"] = bars["close"].rolling(10, min_periods=10).mean()
    return bars


def direction(current: float, previous: float) -> str:
    if current > previous:
        return "上升"
    if current < previous:
        return "下降"
    return "走平"


def window_break(bars: pd.DataFrame, recent: int, previous: int) -> dict | None:
    """最近 recent 根 与 再向前 previous 根 的极值突破（严格不等）。"""
    required = recent + previous
    if len(bars) < required:
        return None
    recent_bars = bars.iloc[-recent:]
    previous_bars = bars.iloc[-required:-recent]
    recent_high = float(recent_bars["high"].max())
    previous_high = float(previous_bars["high"].max())
    recent_low = float(recent_bars["low"].min())
    previous_low = float(previous_bars["low"].min())
    return {
        "up": recent_high > previous_high,
        "down": recent_low < previous_low,
        "recent_high": recent_high,
        "previous_high": previous_high,
        "recent_low": recent_low,
        "previous_low": previous_low,
    }


def day_structure(daily: pd.DataFrame) -> dict | None:
    """昨天先形成结构，最新日K不得破坏昨天的结构点。"""
    if len(daily) < 3:
        return None
    current, previous, prior = daily.iloc[-1], daily.iloc[-2], daily.iloc[-3]
    return {
        "higher_low": bool(previous.low > prior.low and current.low >= previous.low),
        "lower_high": bool(previous.high < prior.high and current.high <= previous.high),
        "current": current,
        "previous": previous,
        "prior": prior,
    }


def liquidity_check(latest: pd.Series, price_date: date, volume_min: int, oi_min: int) -> tuple[bool, str]:
    """当前具体主力最新完成交易日的成交量与持仓量硬门。"""
    volume = latest.get("volume")
    interest = latest.get("open_interest")
    if pd.isna(volume) or pd.isna(interest):
        return False, "成交量或持仓量缺失"
    bar_date = pd.Timestamp(latest["date"]).date()
    if bar_date != price_date:
        return False, f"量仓日期 {bar_date} 与技术行情日期 {price_date} 不一致"
    volume = float(volume)
    interest = float(interest)
    if volume <= volume_min and interest <= oi_min:
        return False, f"成交量 {volume:,.0f} 手 ≤ {volume_min:,}，持仓量 {interest:,.0f} 手 ≤ {oi_min:,}"
    if volume <= volume_min:
        return False, f"成交量 {volume:,.0f} 手 ≤ {volume_min:,}"
    if interest <= oi_min:
        return False, f"持仓量 {interest:,.0f} 手 ≤ {oi_min:,}"
    return True, ""


# ---------------------------------------------------------------- 三模式判定

def classify_modes(signals: dict) -> dict[str, str]:
    """按三个模式独立分类；此处不含量仓硬门（由 apply_liquidity 施加）。"""
    month_up = signals["month_direction"] == "上升"
    month_down = signals["month_direction"] == "下降"
    week_up = signals["week_direction"] == "上升"
    week_down = signals["week_direction"] == "下降"
    day_up = signals["day_direction"] == "上升"
    day_down = signals["day_direction"] == "下降"

    month_break_up = signals["month_break_up"]
    month_break_down = signals["month_break_down"]
    week_break_up = signals["week_break_up"]
    week_break_down = signals["week_break_down"]
    resonance_available = signals.get("month_resonance_break_available", True)
    resonance_break_up = signals.get("month_resonance_break_up", month_break_up)
    resonance_break_down = signals.get("month_resonance_break_down", month_break_down)

    return {
        "month-week": (
            STATUS_INSUFFICIENT if not signals.get("month_break_available", True) else
            "多头观察" if month_up and week_up and signals["week_higher_low"] and month_break_up else
            "空头观察" if month_down and week_down and signals["week_lower_high"] and month_break_down else
            STATUS_EXCLUDED
        ),
        "week-day": (
            "多头观察" if week_up and day_up and signals["day_higher_low"] and week_break_up else
            "空头观察" if week_down and day_down and signals["day_lower_high"] and week_break_down else
            STATUS_EXCLUDED
        ),
        # 月周日共振使用独立的3个月对比前12个月突破，不再要求日K高低点结构。
        "month-week-day": (
            STATUS_INSUFFICIENT if not resonance_available else
            "多头观察" if month_up and week_up and day_up and resonance_break_up else
            "空头观察" if month_down and week_down and day_down and resonance_break_down else
            STATUS_EXCLUDED
        ),
    }


def apply_liquidity(modes: dict[str, str]) -> dict[str, str]:
    """硬门不合格时，三个模式统一失去观察资格。"""
    return {mode: STATUS_ILLIQUID for mode in modes}


def analyze(product: dict, main_contract: str | None, config: dict, as_of: date,
            closing_snapshot: dict | None = None, cache_dir=None, no_trade_source=None) -> dict:
    base = {key: product[key] for key in ("code", "name", "exchange", "sector")}
    liquidity_conf = config.get("liquidity", {})
    volume_min = int(liquidity_conf.get("volume_min", DEFAULT_VOLUME_MIN))
    oi_min = int(liquidity_conf.get("open_interest_min", DEFAULT_OI_MIN))
    breakout_conf = {**DEFAULT_BREAKOUT, **config.get("breakout", {})}

    try:
        if no_trade_source:
            base.update(no_trade=True, data_date=as_of.isoformat(), data_source=no_trade_source,
                        volume=0, open_interest=0, market_current=False)
            raise ValueError("交易所当日全部合约零成交、零持仓，无可用收盘K线")
        if not main_contract:
            raise ValueError("未取得当前具体主力合约")

        continuous_symbol = f"{product['code']}0"
        continuous = fetch_sina(continuous_symbol)
        specific = fetch_sina(main_contract)
        specific = (merge_close(specific, main_contract, closing_snapshot, cache_dir, as_of)
                    if cache_dir is not None else upsert_daily_bar(specific, closing_snapshot))
        continuous = continuous[continuous["date"].dt.date <= as_of].sort_values("date").reset_index(drop=True)
        specific = specific[specific["date"].dt.date <= as_of].sort_values("date").reset_index(drop=True)
        if continuous.empty or specific.empty:
            raise ValueError("没有截至扫描日的日K")

        latest_specific_date = pd.Timestamp(specific.iloc[-1]["date"]).date()
        if latest_specific_date != as_of:
            base.update(data_date=latest_specific_date.isoformat(), market_current=False)
            raise ValueError(f"当日收盘数据待补：目标 {as_of}，实际 {latest_specific_date}")
        base.update(market_current=True, data_date=latest_specific_date.isoformat(),
                    data_source=str(specific.iloc[-1].get("source", "新浪历史日K")),
                    provisional=bool(specific.iloc[-1].get("provisional", False)))
        if (as_of - latest_specific_date).days > int(config.get("max_data_age_days", 7)):
            raise ValueError(f"当前具体主力数据陈旧：{latest_specific_date}")

        # 月线极值：主力连续提供长期历史，当前动态月K用当前具体主力校正。
        # 月MA10方向：优先使用当前具体主力合约的月K。文华主力图的MA10
        # 是按当前主力合约自身月收盘序列计算；不能用主力连续换月序列替代。
        monthly = aggregate_bars(continuous, "M", completed_only=False, as_of=as_of)
        current_month_period = pd.Period(specific.iloc[-1]["date"], freq="M")
        if current_month_period not in monthly.index:
            raise ValueError("主力连续缺少当前月数据")
        month_bars = specific[specific["date"].dt.to_period("M") == current_month_period]
        if month_bars.empty:
            raise ValueError("当前具体主力缺少当月数据")
        monthly.loc[current_month_period, "open"] = float(month_bars.iloc[0]["open"])
        monthly.loc[current_month_period, "high"] = float(month_bars["high"].max())
        monthly.loc[current_month_period, "low"] = float(month_bars["low"].min())
        monthly.loc[current_month_period, "close"] = float(month_bars.iloc[-1]["close"])
        monthly["ma10"] = monthly["close"].rolling(10, min_periods=10).mean()

        specific_monthly = aggregate_bars(specific, "M", completed_only=False, as_of=as_of)
        specific_monthly["ma10"] = specific_monthly["close"].rolling(10, min_periods=10).mean()
        if len(specific_monthly) >= 11:
            monthly.loc[specific_monthly.index, "ma10"] = specific_monthly["ma10"]

        # 动态周K用于方向和结构，避免本周破位后仍沿用上周的旧判断。
        weekly = aggregate_bars(specific, "W-FRI", completed_only=False, as_of=as_of)
        completed_weekly = aggregate_bars(specific, "W-FRI", completed_only=True, as_of=as_of)
        daily = specific.copy()
        daily["ma10"] = daily["close"].rolling(10, min_periods=10).mean()

        if len(monthly) < 11:
            raise ValueError("月K MA10样本不足")
        if len(weekly) < 11:
            raise ValueError("动态周K MA10样本不足")
        if len(daily) < 11:
            raise ValueError("完成日K MA10样本不足")

        month_break = window_break(monthly, breakout_conf["month_recent"], breakout_conf["month_previous"])
        resonance_month_break = window_break(
            monthly,
            breakout_conf["resonance_month_recent"],
            breakout_conf["resonance_month_previous"],
        )
        week_break = window_break(completed_weekly, breakout_conf["week_recent"], breakout_conf["week_previous"])
        if week_break is None:
            raise ValueError("周线突破样本不足8个完成周")

        current_month, previous_month = monthly.iloc[-1], monthly.iloc[-2]
        current_week, previous_week = weekly.iloc[-1], weekly.iloc[-2]
        current_day, previous_day, prior_day = daily.iloc[-1], daily.iloc[-2], daily.iloc[-3]
        day_pattern = day_structure(daily)
        if day_pattern is None:
            raise ValueError("日K结构样本不足3根")

        signals = {
            "month_direction": direction(float(current_month.ma10), float(previous_month.ma10)),
            "week_direction": direction(float(current_week.ma10), float(previous_week.ma10)),
            "day_direction": direction(float(current_day.ma10), float(previous_day.ma10)),
            "week_higher_low": bool(current_week.low > previous_week.low),
            "week_lower_high": bool(current_week.high < previous_week.high),
            "day_higher_low": day_pattern["higher_low"],
            "day_lower_high": day_pattern["lower_high"],
            "month_break_available": month_break is not None,
            "month_break_up": bool(month_break and month_break["up"]),
            "month_break_down": bool(month_break and month_break["down"]),
            "month_resonance_break_available": resonance_month_break is not None,
            "month_resonance_break_up": bool(resonance_month_break and resonance_month_break["up"]),
            "month_resonance_break_down": bool(resonance_month_break and resonance_month_break["down"]),
            "week_break_up": week_break["up"],
            "week_break_down": week_break["down"],
        }
        technical_modes = classify_modes(signals)

        liquidity_ok, liquidity_reason = liquidity_check(
            specific.iloc[-1], latest_specific_date, volume_min, oi_min
        )
        if not liquidity_ok and liquidity_reason == "成交量或持仓量缺失":
            raise ValueError(liquidity_reason)

        base.update({
            "ok": True,
            "main_contract": main_contract,
            "data_date": latest_specific_date.isoformat(),
            "volume_date": latest_specific_date.isoformat(),
            "open_interest_date": latest_specific_date.isoformat(),
            "volume": float(specific.iloc[-1]["volume"]),
            "open_interest": float(specific.iloc[-1]["open_interest"]),
            "liquidity_ok": liquidity_ok,
            "liquidity_reason": liquidity_reason,
            "month_period": str(monthly.index[-1]),
            "week_period": str(weekly.index[-1]),
            "day_period": pd.Timestamp(current_day["date"]).date().isoformat(),
            "month_ma10": float(current_month.ma10),
            "previous_month_ma10": float(previous_month.ma10),
            "week_ma10": float(current_week.ma10),
            "previous_week_ma10": float(previous_week.ma10),
            "day_ma10": float(current_day.ma10),
            "previous_day_ma10": float(previous_day.ma10),
            "week_low": float(current_week.low),
            "previous_week_low": float(previous_week.low),
            "week_high": float(current_week.high),
            "previous_week_high": float(previous_week.high),
            "day_low": float(current_day.low),
            "previous_day_low": float(previous_day.low),
            "prior_day_low": float(prior_day.low),
            "day_high": float(current_day.high),
            "previous_day_high": float(previous_day.high),
            "prior_day_high": float(prior_day.high),
            "prior_day_date": pd.Timestamp(prior_day["date"]).date().isoformat(),
            "previous_day_date": pd.Timestamp(previous_day["date"]).date().isoformat(),
            "latest_bar": {key: float(current_day[key]) for key in ("open", "high", "low", "close", "volume", "open_interest")},
            "month_break_recent_high": month_break["recent_high"] if month_break else None,
            "month_break_previous_high": month_break["previous_high"] if month_break else None,
            "month_break_recent_low": month_break["recent_low"] if month_break else None,
            "month_break_previous_low": month_break["previous_low"] if month_break else None,
            "month_resonance_break_recent_high": (
                resonance_month_break["recent_high"] if resonance_month_break else None
            ),
            "month_resonance_break_previous_high": (
                resonance_month_break["previous_high"] if resonance_month_break else None
            ),
            "month_resonance_break_recent_low": (
                resonance_month_break["recent_low"] if resonance_month_break else None
            ),
            "month_resonance_break_previous_low": (
                resonance_month_break["previous_low"] if resonance_month_break else None
            ),
            "week_break_recent_high": week_break["recent_high"],
            "week_break_previous_high": week_break["previous_high"],
            "week_break_recent_low": week_break["recent_low"],
            "week_break_previous_low": week_break["previous_low"],
            **signals,
            "technical_modes": technical_modes,
            "modes": technical_modes if liquidity_ok else apply_liquidity(technical_modes),
        })
        # 新层失败不得抹掉已经计算出的原三模式资格；全部使用同一次行情，无额外网络请求。
        try:
            month_daily = pd.concat([
                continuous[continuous["date"].dt.to_period("M") != current_month_period], month_bars
            ]).sort_values("date").reset_index(drop=True)
            base.update(attention.evaluate(base, monthly, weekly, completed_weekly, daily, month_daily, config))
        except Exception as exc:  # noqa: BLE001
            base["attention"] = {
                key: {"tier": "数据待核", "state": "关注层计算失败", "side": value if value in SIDES else None,
                      "baseline_qualified": value in SIDES, "reasons": [f"{type(exc).__name__}: {exc}"]}
                for key, value in base["modes"].items()
            }
    except Exception as exc:  # noqa: BLE001
        base.update({
            "ok": False,
            "main_contract": main_contract,
            "error": f"{type(exc).__name__}: {exc}",
            "technical_modes": {mode: STATUS_INSUFFICIENT for mode in MODE_LABELS},
            "modes": {mode: STATUS_INSUFFICIENT for mode in MODE_LABELS},
            "long_term_position": {},
            "attention": {
                mode: {
                    "tier": "数据待核",
                    "state": "基础数据不足",
                    "side": None,
                    "baseline_qualified": False,
                    "reasons": [f"{type(exc).__name__}: {exc}"],
                }
                for mode in MODE_LABELS
            },
        })
    return base


# ---------------------------------------------------------------- 报告

def selected_modes(mode: str) -> list[str]:
    return list(MODE_LABELS) if mode == "all" else [mode]


def mode_reason(row: dict, mode: str) -> str:
    if not row.get("ok"):
        return row.get("error", STATUS_INSUFFICIENT)
    if not row.get("liquidity_ok"):
        return row["liquidity_reason"]
    side = row["modes"][mode]
    if side == STATUS_INSUFFICIENT:
        return ("月周大周期所需15个月月K样本不足" if mode == "month-week" else
                "月周日共振所需的前12个月月K样本不足")
    if side == "多头观察":
        structure = "周低点抬高" if mode == "month-week" else ("日低点抬高" if mode == "week-day" else "不要求日K高低点结构")
        periods = "月、周" if mode == "month-week" else ("周、日" if mode == "week-day" else "月、周、日")
        breakout = ("最近3月创15个月新高" if mode == "month-week" else
                    "最近3周创8周新高" if mode == "week-day" else
                    "最近3月最高价高于前12个月最高价")
        return f"{periods}MA10上升；{structure}；{breakout}"
    if side == "空头观察":
        structure = "周高点降低" if mode == "month-week" else ("日高点降低" if mode == "week-day" else "不要求日K高低点结构")
        periods = "月、周" if mode == "month-week" else ("周、日" if mode == "week-day" else "月、周、日")
        breakout = ("最近3月创15个月新低" if mode == "month-week" else
                    "最近3周创8周新低" if mode == "week-day" else
                    "最近3月最低价低于前12个月最低价")
        return f"{periods}MA10下降；{structure}；{breakout}"
    return "方向、最小周期结构或极值突破未同时满足"


def fmt_price(value: float | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    value = float(value)
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:,.2f}"
    return f"{value:,.3f}"


def structure_cell(higher_low: bool, lower_high: bool) -> str:
    return f"低{'↑' if higher_low else '－'} 高{'↓' if lower_high else '－'}"


def breakout_cell(up: bool, down: bool) -> str:
    if up and down:
        return "新高/新低"
    if up:
        return "新高"
    if down:
        return "新低"
    return "—"


def grouped_candidates(rows: list[dict], mode: str, side: str, sector_order: list[str]) -> list[str]:
    lines: list[str] = []
    for sector in sector_order:
        matched = [row for row in rows if row.get("sector") == sector and row.get("modes", {}).get(mode) == side]
        if matched:
            names = "、".join(f"{row['name']}（{row['code']}）" for row in matched)
            lines.append(f"- {sector}：{names}")
    return lines or ["无"]


def candidate_detail_table(rows: list[dict], mode: str, side: str, sector_order: list[str]) -> list[str]:
    order = {sector: index for index, sector in enumerate(sector_order)}
    matched = [row for row in rows if row.get("modes", {}).get(mode) == side]
    matched.sort(key=lambda row: order.get(row.get("sector"), len(order)))
    if not matched:
        return ["无", ""]
    month_high_header = "3月高／前12高" if mode == "month-week-day" else "3月高／前5高"
    month_low_header = "3月低／前12低" if mode == "month-week-day" else "3月低／前5低"
    lines = [
        f"| 品种 | 板块 | 主力合约 | 成交量 | 持仓量 | 月MA10 | 周MA10 | 日MA10 | 周结构 | 日结构 | {month_high_header} | {month_low_header} | 3周高／前5高 | 3周低／前5低 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in matched:
        month_recent_high = row.get("month_resonance_break_recent_high") if mode == "month-week-day" else row.get("month_break_recent_high")
        month_previous_high = row.get("month_resonance_break_previous_high") if mode == "month-week-day" else row.get("month_break_previous_high")
        month_recent_low = row.get("month_resonance_break_recent_low") if mode == "month-week-day" else row.get("month_break_recent_low")
        month_previous_low = row.get("month_resonance_break_previous_low") if mode == "month-week-day" else row.get("month_break_previous_low")
        lines.append(
            f"| {row['name']}（{row['code']}） | {row['sector']} | {row['main_contract']} | "
            f"{row['volume']:,.0f} | {row['open_interest']:,.0f} | "
            f"{row['month_direction']} | {row['week_direction']} | {row['day_direction']} | "
            f"{structure_cell(row['week_higher_low'], row['week_lower_high'])} | "
            f"{structure_cell(row['day_higher_low'], row['day_lower_high'])} | "
            f"{fmt_price(month_recent_high)}／{fmt_price(month_previous_high)} | "
            f"{fmt_price(month_recent_low)}／{fmt_price(month_previous_low)} | "
            f"{fmt_price(row['week_break_recent_high'])}／{fmt_price(row['week_break_previous_high'])} | "
            f"{fmt_price(row['week_break_recent_low'])}／{fmt_price(row['week_break_previous_low'])} |"
        )
    lines.append("")
    return lines


def details_table(rows: list[dict], modes: list[str]) -> list[str]:
    mode_headers = " | ".join(MODE_LABELS[mode] for mode in modes)
    lines = [
        f"| 品种 | 板块 | 主力 | 成交量 | 持仓量 | 月 | 周 | 日 | 周结构 | 日结构 | 月突破 | 共振月突破 | 周突破 | {mode_headers} |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|" + "---|" * len(modes),
    ]
    for row in rows:
        if not row.get("ok"):
            statuses = " | ".join(STATUS_INSUFFICIENT for _ in modes)
            lines.append(
                f"| {row['name']}（{row['code']}） | {row['sector']} | — | — | — | — | — | — | — | — | — | — | — | {statuses} |"
            )
            continue
        statuses = " | ".join(row["modes"][mode] for mode in modes)
        lines.append(
            f"| {row['name']}（{row['code']}） | {row['sector']} | {row['main_contract']} | "
            f"{row['volume']:,.0f} | {row['open_interest']:,.0f} | "
            f"{row['month_direction']} | {row['week_direction']} | {row['day_direction']} | "
            f"{structure_cell(row['week_higher_low'], row['week_lower_high'])} | "
            f"{structure_cell(row['day_higher_low'], row['day_lower_high'])} | "
            f"{breakout_cell(row['month_break_up'], row['month_break_down'])} | "
            f"{breakout_cell(row.get('month_resonance_break_up', False), row.get('month_resonance_break_down', False))} | "
            f"{breakout_cell(row['week_break_up'], row['week_break_down'])} | {statuses} |"
        )
    return lines


def build_report(rows: list[dict], config: dict, as_of: date, mode: str) -> tuple[str, dict]:
    modes = selected_modes(mode)
    available = [row for row in rows if row.get("ok")]
    missing = [row for row in rows if not row.get("ok")]
    liquid = [row for row in available if row.get("liquidity_ok")]
    illiquid = [row for row in available if not row.get("liquidity_ok")]

    data_date = max((row["data_date"] for row in available), default=as_of.isoformat())
    counts = {
        selected: {
            "technical_long": sum(row["technical_modes"][selected] == "多头观察" for row in available),
            "technical_short": sum(row["technical_modes"][selected] == "空头观察" for row in available),
            "long": sum(row["modes"][selected] == "多头观察" for row in available),
            "short": sum(row["modes"][selected] == "空头观察" for row in available),
            "excluded": sum(row["modes"][selected] == STATUS_EXCLUDED for row in available),
            "illiquid": sum(row["modes"][selected] == STATUS_ILLIQUID for row in available),
        }
        for selected in modes
    }

    output = [
        "# 五简期货多周期筛选｜一包三模式 v2.5.1", "",
        "## 数据概览", "",
        f"- 扫描截点：{as_of.isoformat()}",
        f"- 最新技术行情日期：{data_date}",
        f"- 成交量、持仓量数据日期：{data_date}（取自当前具体主力合约同一根完成日K）",
        f"- 品种范围：配置内 {len(config['products'])} 个国内期货品种；技术数据成功 {len(available)} 个；数据不足 {len(missing)} 个",
        f"- 流动性硬门（成交量>2万手且持仓量>2万手）：通过 {len(liquid)} 个；不合格 {len(illiquid)} 个",
        "- 月K、周K均动态更新至最新日K；周线8周突破窗口仍只使用完成自然周",
        "- 周日小周期保留日K结构；月周日共振只要求月、周、日MA10方向和独立月线突破，不再要求日K低点抬高或高点降低",
        "- 板块只分组展示，不参与纳入、否决或排序",
        "- 未使用：价格与MA10位置、量仓趋势解释、供需、基本面、板块强弱、综合斜率排名",
        "- 新增关注层：12个月相对位置，8/18个月旁证，固定事件边界、紧凑整理与推进状态；不改各模式硬条件",
        "- 长期位置来自主力连续研究序列，可能受换月价差影响，需核对具体合约；关注层参数未经绩效验证",
        "",
    ]

    output.extend(attention.report_lines(rows, modes, config["sector_order"]))

    for selected in modes:
        label = MODE_LABELS[selected]
        statistic = counts[selected]
        output.extend([
            f"## 原始模式资格：{label}", "",
            f"- 过滤前（仅技术条件）：多头 {statistic['technical_long']} 个；空头 {statistic['technical_short']} 个",
            f"- 过滤后（加流动性硬门）：多头 {statistic['long']} 个；空头 {statistic['short']} 个；"
            f"未纳入 {statistic['excluded']} 个；流动性不合格 {statistic['illiquid']} 个",
            "",
            "### 多头观察（按板块分组）", "",
            *grouped_candidates(rows, selected, "多头观察", config["sector_order"]), "",
            "### 多头观察明细", "",
            *candidate_detail_table(rows, selected, "多头观察", config["sector_order"]),
            "### 空头观察（按板块分组）", "",
            *grouped_candidates(rows, selected, "空头观察", config["sector_order"]), "",
            "### 空头观察明细", "",
            *candidate_detail_table(rows, selected, "空头观察", config["sector_order"]),
        ])

    if mode == "all":
        multi_hits = []
        for row in available:
            hits = [
                f"{MODE_LABELS[key]}-{value.replace('观察', '')}"
                for key, value in row["modes"].items()
                if value in SIDES
            ]
            if len(hits) > 1:
                multi_hits.append(f"- {row['name']}（{row['code']}）：{'、'.join(hits)}")
        output.extend(["## 多模式命中", "", *(multi_hits or ["无"]), ""])

        divergence = []
        for row in available:
            if not row.get("liquidity_ok"):
                continue
            if row["modes"]["month-week-day"] not in SIDES or row["modes"]["week-day"] in SIDES:
                continue
            side = row["modes"]["month-week-day"]
            if side == "多头观察":
                detail = (f"共振3月高 {fmt_price(row.get('month_resonance_break_recent_high'))} / 前12月高 "
                          f"{fmt_price(row.get('month_resonance_break_previous_high'))}；周日小周期另需周线8周突破和日K结构")
            else:
                detail = (f"共振3月低 {fmt_price(row.get('month_resonance_break_recent_low'))} / 前12月低 "
                          f"{fmt_price(row.get('month_resonance_break_previous_low'))}；周日小周期另需周线8周突破和日K结构")
            divergence.append(f"- {row['name']}（{row['code']}）{side}：{detail}")
        output.extend([
            "## 共振与周日的口径差异", "",
            "下列品种符合新的月周日共振，但不符合周日小周期；两者的月线突破窗口和日K结构要求不同："
            "共振使用最近3个月对比前12个月，周日小周期使用最近3个完成周对比前5个完成周并要求日K结构。", "",
            *(divergence or ["无"]), "",
        ])

    output.extend(["## 因流动性硬门被过滤的品种", ""])
    if illiquid:
        output.extend([
            "| 品种 | 板块 | 主力合约 | 成交量 | 持仓量 | 过滤原因 |",
            "|---|---|---|---|---|---|",
            *[
                f"| {row['name']}（{row['code']}） | {row['sector']} | {row['main_contract']} | "
                f"{row['volume']:,.0f} | {row['open_interest']:,.0f} | {row['liquidity_reason']} |"
                for row in illiquid
            ],
            "",
        ])
    else:
        output.extend(["无", ""])

    output.extend(["## 数据不足", ""])
    if missing:
        output.extend([f"- {row['name']}（{row['code']}）：{row.get('error', '未知错误')}" for row in missing] + [""])
    else:
        output.extend(["无", ""])

    output.extend([
        "## 全量判定表", "",
        *details_table(rows, modes), "",
        "> 本报告只筛选观察环境，不读取60分钟图，不产生入场、止损、仓位或下单指令。月线在月末收盘前会动态变化。",
    ])

    summary = {
        "rule_version": "v2.5.1",
        "baseline_rule_version": "v2.5.1",
        "attention_parameters": attention.settings(config),
        "attention_counts": attention.counts(rows, modes),
        "target_date": as_of.isoformat(),
        "current_count": sum(row.get("market_current", False) for row in rows),
        "no_trade_count": sum(row.get("no_trade", False) for row in rows),
        "provisional_count": sum(row.get("provisional", False) for row in rows),
        "scan_date": as_of.isoformat(),
        "data_date": data_date,
        "volume_date": data_date,
        "open_interest_date": data_date,
        "universe_size": len(config["products"]),
        "success_count": len(available),
        "missing_count": len(missing),
        "liquid_count": len(liquid),
        "illiquid_count": len(illiquid),
        "selected_modes": modes,
        "counts": counts,
        "rows": rows,
    }
    return "\n".join(output), summary


# ---------------------------------------------------------------- 入口

def main() -> int:
    parser = argparse.ArgumentParser(description="五简国内期货87品种多周期筛选 v2.5.1")
    parser.add_argument("--as-of", default=None, help="扫描截点 YYYY-MM-DD；默认取当前可用日期")
    parser.add_argument("--codes", default=None, help="仅扫描指定代码，逗号分隔，如 SC,FU,BU")
    parser.add_argument("--workers", type=int, default=6, help="并发读取数，默认6")
    parser.add_argument("--mode", choices=["all", *MODE_LABELS], default="all", help="输出全部或指定模式")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    attention.settings(config)  # 参数错误在读取行情前明确失败，不默默使用其他口径。
    products = config["products"]
    if args.codes:
        selected_codes = {code.strip().upper() for code in args.codes.split(",") if code.strip()}
        products = [product for product in products if product["code"].upper() in selected_codes]
        missing_codes = selected_codes - {product["code"].upper() for product in products}
        if missing_codes:
            parser.error(f"配置中不存在品种代码：{','.join(sorted(missing_codes))}")
        config = {**config, "products": products}

    as_of = target_day(resolve_as_of(args.as_of))
    main_contracts = resolve_main_contracts(config)
    print(f"[信息] 扫描截点={as_of} 品种数={len(products)} 模式={args.mode}", flush=True)
    snapshot_dir = Path.cwd() / "source-snapshots" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    closing_spots = collect_closes(products, main_contracts, as_of, snapshot_dir)
    cache_dir = Path.cwd() / "contract-bars"
    print(f"[信息] 当日收盘补充={len(closing_spots)}份合约", flush=True)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(analyze, product, main_contracts.get(product["code"]), config, as_of,
                            closing_spots.get(main_contracts.get(product["code"])), cache_dir,
                            closing_spots.get('_no_trade', {}).get(product['code'])): product
            for product in products
        }
        for index, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            if index % 20 == 0:
                print(f"[信息] 已完成 {index}/{len(products)}", flush=True)

    order = {product["code"]: index for index, product in enumerate(products)}
    rows.sort(key=lambda row: order[row["code"]])
    if not any(row.get('market_current') or row.get('no_trade') for row in rows):
        raise RuntimeError('没有取得目标交易日数据，保留上次扫描结果')
    report, summary = build_report(rows, config, as_of, args.mode)
    summary["source_snapshot"] = str(snapshot_dir)

    output_dir = Path.cwd() / ".wujian-futures-multi-cycle-scan"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.mode == "all" else f"_{args.mode}"
    report_path = output_dir / f"{as_of.isoformat()}{suffix}.md"
    focus_path = output_dir / f"{as_of.isoformat()}{suffix}_关注清单.md"
    data_path = output_dir / f"{as_of.isoformat()}{suffix}.json"
    history_dir = output_dir / "history"
    history_dir.mkdir(exist_ok=True)
    if data_path.exists():
        (history_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")).write_bytes(data_path.read_bytes())
    report_path.write_text(report, encoding="utf-8")
    focus_text = [
        f"# 五简盘后关注清单 {as_of.isoformat()} v2.5.1", "",
        f"数据成功{summary['success_count']}／{summary['universe_size']}；数据不足{summary['missing_count']}；"
        f"临时收盘快照{summary['provisional_count']}（待正式复核）。",
        "位置按窗口高低区间计算，不是距最高价的涨跌幅。关注参数为待验证定义，不是收益承诺。",
        "月线使用主力连续研究历史，换月价差需人工复核；60分钟切入仍由用户自行判断。", "",
        *attention.report_lines(rows, selected_modes(args.mode), config["sector_order"], tiers=("重点关注", "蓄力观察")),
        "## 分层数量与完整证据", "",
        *[f"- {MODE_LABELS[key]}：" + "；".join(f"{label}{value}项" for label, value in values.items())
          for key, values in summary["attention_counts"].items()], "",
        f"完整原始名单、流动性过滤与数据缺口见 [{report_path.name}]({report_path.name})。", "",
    ]
    focus_path.write_text("\n".join(focus_text), encoding="utf-8")
    temporary_path = data_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(data_path)

    print(report)
    print(f"\n[已保存] {report_path}")
    print(f"[已保存] {data_path}")
    print(f"[已保存] {focus_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
