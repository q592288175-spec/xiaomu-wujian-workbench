"""只读价格关注层：保留三模式资格，补充长期位置与当前状态。"""
from __future__ import annotations

import math

import pandas as pd

DEFAULT_ATTENTION = {
    "position_months": 12,
    "position_edge": 0.25,
    "state_lookback": 10,
    "efficiency_min": 0.60,
    "consolidation_bars": 4,
    "consolidation_ratio_max": 0.35,
}
MODE_LABELS = {"month-week": "月周", "week-day": "周日", "month-week-day": "共振"}
TIERS = ("重点关注", "蓄力观察", "暂缓关注", "数据待核", "未纳入")
DEFAULT_BREAKOUT = {
    "month_recent": 3,
    "month_previous": 12,
    "week_recent": 3,
    "week_previous": 5,
    "resonance_month_recent": 3,
    "resonance_month_previous": 12,
}


def settings(config: dict) -> dict:
    result = {**DEFAULT_ATTENTION, **config.get("attention", {})}
    for key in ("position_months", "state_lookback", "consolidation_bars"):
        if not isinstance(result[key], int) or isinstance(result[key], bool):
            raise ValueError(f"关注参数 {key} 必须为整数")
    if result["position_months"] < 8:
        raise ValueError("长期位置主窗口不得少于8个月")
    if not 2 <= result["consolidation_bars"] < result["state_lookback"]:
        raise ValueError("整理根数必须至少2根且小于状态回看根数")
    for key, maximum in (("position_edge", 0.5), ("efficiency_min", 1), ("consolidation_ratio_max", 1)):
        value = result[key]
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value < maximum:
            raise ValueError(f"关注参数 {key} 必须在0与{maximum}之间")
    return result


def _label(frame: pd.DataFrame, index: int) -> str:
    row = frame.iloc[index]
    if isinstance(frame.index, pd.PeriodIndex):
        return str(frame.index[index])
    return str(pd.Timestamp(row["date"]).date())


def positions(monthly: pd.DataFrame, close: float, rule: dict) -> dict:
    result = {}
    for count in sorted({8, 12, 18, rule["position_months"]}):
        entry = {"months": count, "available": False, "position_pct": None}
        result[str(count)] = entry
        if len(monthly) < count:
            entry["reason"] = f"月K不足{count}根"
            continue
        sample = monthly.iloc[-count:]
        if isinstance(sample.index, pd.PeriodIndex) and any(
            right.ordinal - left.ordinal != 1 for left, right in zip(sample.index, sample.index[1:])
        ):
            entry["reason"] = "月K月份不连续"
            continue
        if sample[["high", "low"]].isna().any().any():
            entry["reason"] = "月K极值缺失"
            continue
        high, low = float(sample.high.max()), float(sample.low.min())
        if not all(math.isfinite(value) for value in (high, low, close)) or high <= low:
            entry["reason"] = "区间宽度为零或价格无效"
            continue
        if not low <= close <= high:
            entry["reason"] = "当前收盘不在同源月线区间内，核对合约口径"
            continue
        location = (close - low) / (high - low)
        entry.update(
            available=True, high=high, low=low, position_pct=location * 100,
            location="高位" if location >= 1 - rule["position_edge"] else
                     "低位" if location <= rule["position_edge"] else "区间中部",
            start=_label(sample, 0), end=_label(sample, -1),
            recent_three_new_high=bool(sample.iloc[-3:].high.max() > sample.iloc[:-3].high.max()),
            recent_three_new_low=bool(sample.iloc[-3:].low.min() < sample.iloc[:-3].low.min()),
        )
    return result


def breakout_context(bars: pd.DataFrame, event_daily: pd.DataFrame, daily: pd.DataFrame,
                     side: str, recent: int = 3, previous: int = 5) -> dict:
    """原窗口不改；独立事件的此前窗口固定，避免旧高滚出后伪称新突破。"""
    sign = 1 if side == "多头观察" else -1
    column = "high" if sign == 1 else "low"
    preceding = previous
    for index in range(len(bars) - 1, max(-1, len(bars) - recent - 1), -1):
        if index < preceding:
            continue
        reference = bars.iloc[index - preceding:index]
        boundary = float(reference.high.max() if sign == 1 else reference.low.min())
        extreme = float(bars.iloc[index][column])
        if sign * (extreme - boundary) <= 0:
            continue
        period = bars.index[index]
        within = event_daily[event_daily.date.dt.to_period(period.freqstr) == period]
        crossed = within[sign * (within[column] - boundary) > 0]
        if crossed.empty:
            return {"available": False, "status": "事件待核", "reason": "周期极值与事件日数据不一致"}
        event_date = crossed.iloc[0].date
        after = daily[daily.date >= event_date]
        if after.empty:
            return {"available": False, "status": "事件待核", "reason": "缺少事件后的具体主力收盘数据"}
        distances = sign * (after.close - boundary)
        if distances.iloc[-1] > 0:
            status = "突破保持"
        elif len(distances) >= 2 and (distances.iloc[-2:] < 0).all():
            status = "突破失守"
        else:
            status = "回踩待确认"
        return {
            "available": True, "status": status, "boundary": boundary,
            "event_period": str(period), "event_date": str(pd.Timestamp(event_date).date()),
            "reference_start": _label(reference, 0), "reference_end": _label(reference, -1),
            "close": float(after.iloc[-1].close),
            "last_closes": [float(value) for value in after.close.iloc[-2:]],
        }
    return {"available": False, "status": "事件待核",
            "reason": "原滚动极值条件不等于独立突破，最近窗口无可核验事件"}


def pattern_state(bars: pd.DataFrame, side: str, rule: dict) -> dict:
    count, compact_count = rule["state_lookback"], rule["consolidation_bars"]
    if len(bars) < count + 1:
        return {"available": False, "state": "状态样本不足", "reason": f"状态需{count + 1}根K线"}
    sample = bars.iloc[-count - 1:]
    if (not all(math.isfinite(float(value)) for value in sample[["close", "high", "low"]].to_numpy().flat)
            or (sample.high < sample.low).any()):
        return {"available": False, "state": "状态数据缺失", "reason": "状态窗口价格缺失"}
    reference, current = sample.iloc[:-1], sample.iloc[-1]
    box = reference.iloc[-compact_count:]
    high, low = float(box.high.max()), float(box.low.min())
    whole_range = float(reference.high.max() - reference.low.min())
    if whole_range <= 0:
        return {"available": False, "state": "状态无法计算", "reason": "状态参考区间宽度为零"}
    ratio = (high - low) / whole_range
    sign = 1 if side == "多头观察" else -1
    changes = sample.close.diff().dropna() * sign
    path = float(changes.abs().sum())
    efficiency = float(changes.sum()) / path if path else 0.0
    advancing = int((changes > 0).sum())
    compact = ratio <= rule["consolidation_ratio_max"]
    edge = high if sign == 1 else low
    forward = float(changes.iloc[-1]) > 0
    if compact and sign * (float(current.close) - edge) > 0 and forward:
        state = "蓄力后上破" if sign == 1 else "蓄力后下破"
    elif compact and low <= current.close <= high:
        intact = current.low >= low if sign == 1 else current.high <= high
        wick_break = current.high > high if sign == 1 else current.low < low
        if not intact:
            state = "回撤待确认"
        elif wick_break:
            state = "上破未站稳" if sign == 1 else "下破未站稳"
        else:
            state = "高位整理" if sign == 1 else "低位整理"
    elif (efficiency >= rule["efficiency_min"] and advancing >= math.ceil(count * 0.6)
          and not (changes.iloc[-2:] < 0).all() and forward):
        state = "持续清晰推进"
    else:
        state = "推进放缓/反复"
    return {
        "available": True, "state": state, "efficiency": efficiency,
        "advancing_bars": advancing, "lookback": count,
        "box_high": high, "box_low": low, "box_ratio": ratio, "compact": compact,
        "box_start": _label(box, 0), "box_end": _label(box, -1),
    }


def environment_side(row: dict, mode: str) -> str | None:
    """识别关注层方向基础；使用各模式自己的月线突破窗口。"""
    periods = ("month", "week") if mode == "month-week" else (
        ("week", "day") if mode == "week-day" else ("month", "week", "day"))
    breakout_prefix = "week_break" if mode == "week-day" else (
        "month_resonance_break" if mode == "month-week-day" else "month_break"
    )
    for side, direction, suffix in (("多头观察", "上升", "up"), ("空头观察", "下降", "down")):
        if all(row[f"{period}_direction"] == direction for period in periods) and row.get(f"{breakout_prefix}_{suffix}", False):
            return side
    return None


def evaluate(row: dict, monthly: pd.DataFrame, weekly: pd.DataFrame, completed_weekly: pd.DataFrame,
             daily: pd.DataFrame, month_daily: pd.DataFrame, config: dict) -> dict:
    rule = settings(config)
    location = positions(monthly, float(daily.iloc[-1].close), rule)
    results = {}
    for mode in MODE_LABELS:
        side = environment_side(row, mode)
        qualified = row["modes"][mode] in ("多头观察", "空头观察")
        item = {"side": side, "baseline_qualified": qualified, "tier": "未纳入", "state": "原条件未满足",
                "reasons": [], "position_months": rule["position_months"], "dynamic_week": mode == "month-week"}
        results[mode] = item
        if not row["liquidity_ok"]:
            item["reasons"].append(row["liquidity_reason"])
            continue
        if not side:
            item["reasons"].append("原模式方向或突破条件未满足")
            continue
        item["tier"] = "暂缓关注"
        wanted = "上升" if side == "多头观察" else "下降"
        if row["month_direction"] != wanted:
            item.update(state="月线方向不一致", reasons=["保留原周日资格，但不进入顺大趋势关注池"])
            continue
        primary = location[str(rule["position_months"])]
        if not primary["available"]:
            item.update(tier="数据待核", state="长期位置待核", reasons=[primary["reason"]])
            continue
        wanted_location = "高位" if side == "多头观察" else "低位"
        if primary["location"] != wanted_location:
            item.update(state="长期位置不合适", reasons=[f"{rule['position_months']}个月位置{primary['position_pct']:.1f}%，未处于{wanted_location}"])
            continue
        extra = location["18"]
        if not extra["available"]:
            item["reasons"].append("18个月旁证不足，不替代12个月判断")
        elif extra["location"] != wanted_location:
            item["reasons"].append(f"18个月旁证为{extra['location']}，长期位置分歧需人工复核")
        breakout_rule = {**DEFAULT_BREAKOUT, **config.get("breakout", {})}
        period = "week" if mode == "week-day" else "month"
        if mode == "month-week-day":
            recent = breakout_rule["resonance_month_recent"]
            previous = breakout_rule["resonance_month_previous"]
        else:
            recent = breakout_rule[f"{period}_recent"]
            previous = breakout_rule[f"{period}_previous"]
        context = breakout_context(
            completed_weekly if period == "week" else monthly,
            daily if period == "week" else month_daily, daily, side,
            recent, previous,
        )
        item["breakout"] = context
        if not context["available"]:
            item.update(tier="数据待核", state="突破边界待核")
            item["reasons"].append(context["reason"])
            continue
        if context["status"] != "突破保持":
            item["state"] = context["status"]
            item["reasons"].append(f"固定边界{context['boundary']:g}；现收盘{context['close']:g}")
            continue
        pattern = pattern_state(weekly if mode == "month-week" else daily, side, rule)
        item["pattern"] = pattern
        item["state"] = pattern["state"]
        if not pattern["available"]:
            item["tier"] = "数据待核"
            item["reasons"].append(pattern["reason"])
        elif pattern["state"] in ("高位整理", "低位整理"):
            item["tier"] = "蓄力观察"
            item["reasons"].append("仅描述紧凑整理，等待收盘表态，不预判突破")
            if not qualified:
                item["reasons"].append(
                    "周日小周期原日K结构尚未成立，不是正式模式候选"
                    if mode == "week-day" else "原共振方向或月线突破条件尚未成立，不是正式模式候选"
                )
        elif qualified and pattern["state"] in ("蓄力后上破", "蓄力后下破", "持续清晰推进"):
            item["tier"] = "重点关注"
            item["reasons"].append("原模式合格、长期位置合适、突破保持")
        elif not qualified:
            item["reasons"].append(
                "周日小周期原日K结构尚未成立，不进入重点"
                if mode == "week-day" else "原共振方向或月线突破条件尚未成立，不进入重点"
            )
        else:
            item["reasons"].append("当前推进不够清晰，保留原名单供复核")
        if mode == "month-week":
            item["reasons"].append("当前周动态判定，未完成周以周收盘再核")
    return {"long_term_position": location, "attention": results}


def counts(rows: list[dict], modes: list[str]) -> dict:
    return {mode: {tier: sum(row.get("attention", {}).get(mode, {}).get("tier") == tier for row in rows)
                   for tier in TIERS} for mode in modes}


def report_lines(rows: list[dict], modes: list[str], sector_order: list[str],
                 tiers: tuple[str, ...] = TIERS[:-1]) -> list[str]:
    lines = ["## 每日关注首页", "",
             "三种模式按各自规则计算；下列关注层另检查长期位置、月线背景、突破保持与当前形态。",
             "蓄力观察不是开仓许可；原结构未成立的等待项不计入原模式合格数量。", ""]
    for tier in tiers:
        lines.extend([f"### {tier}", ""])
        found = False
        for sector in sector_order:
            records = [(row, mode, row.get("attention", {}).get(mode, {}))
                       for row in rows if row.get("sector") == sector for mode in modes
                       if row.get("attention", {}).get(mode, {}).get("tier") == tier]
            if not records:
                continue
            found = True
            lines.extend([f"#### {sector}", "",
                          "| 品种／主力 | 模式方向 | 8／12／18月位置 | 当前状态 | 原资格 | 原因与核对点 |",
                          "|---|---|---|---|---|---|"])
            for row, mode, item in records:
                places = row.get("long_term_position", {})
                values = [f"{places[str(n)]['position_pct']:.1f}%" if places.get(str(n), {}).get("available")
                          else "不足" for n in (8, 12, 18)]
                direction = (item.get("side") or "待核").replace("观察", "")
                lines.append(f"| {row['name']}／{row.get('main_contract', '待核')} | {MODE_LABELS[mode]}{direction} | "
                             f"{'／'.join(values)} | {item['state']} | "
                             f"{'已通过' if item.get('baseline_qualified') else '未通过'} | {'；'.join(item['reasons'])} |")
            lines.append("")
        if not found:
            lines.extend(["暂无", ""])
    return lines
