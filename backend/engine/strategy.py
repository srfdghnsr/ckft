# -*- coding: utf-8 -*-
"""
六条规则策略引擎（参数化）。
输入：某标的日线 bars、参数 p、冷却信息、交易时段/事件开关。
输出：ENTRY / EXIT 信号（dict），由 scheduler + matcher 执行。
"""
from backend.engine import indicators as ind


def _prev_bars_high_max(bars, n, end_idx):
    window = [b["high"] for b in bars[max(0, end_idx - n):end_idx]]
    return max(window) if window else 0.0


def evaluate_entry(symbol, bars, p, cooldown_active, time_ok, event_ok, has_position):
    """
    规则一+二+三+四+五+六 综合判定入场。
    返回 ENTRY 信号 dict 或 None。
    """
    if has_position:
        return None  # 规则三：不加仓（已持仓忽略买入）
    if not time_ok or not event_ok:
        return None  # 规则六：避开开盘/收盘缓冲与重要事件
    if cooldown_active:
        return None  # 规则五：亏损后冷却
    if len(bars) < int(p["breakout_n"]) + 2:
        return None

    sig = bars[-1]

    # 规则一：强势信号K线 + 突破
    strong = ind.is_strong_bar(sig, bars, p)
    breakout = ind.is_breakout(sig, bars, p)

    # 规则二：第2入场点（突破后的回踩企稳）
    n = int(p["breakout_n"])
    prev_high_max = _prev_bars_high_max(bars, n, len(bars) - 1)
    pullback_level = prev_high_max
    tol = pullback_level * (p["pullback_tol_pct"] / 100.0)
    is_pullback = (pullback_level - tol <= sig["close"] <= pullback_level + tol
                   and sig["close"] >= sig["open"])  # 收阳企稳
    # 回踩需发生在突破之后（存在过突破）
    had_breakout = any(bars[i]["close"] > _prev_bars_high_max(bars, n, i)
                       for i in range(2, len(bars)))

    if strong and breakout:
        entry_ref = sig["close"]
        stop = ind.protective_stop(entry_ref, sig, bars, p)
        return {"type": "ENTRY", "symbol": symbol, "side": "BUY",
                "entry_ref": entry_ref, "stop": stop, "rule": "R1", "bar_date": sig["date"]}
    if had_breakout and is_pullback:
        entry_ref = sig["close"]
        stop = ind.protective_stop(entry_ref, sig, bars, p)
        return {"type": "ENTRY", "symbol": symbol, "side": "BUY",
                "entry_ref": entry_ref, "stop": stop, "rule": "R2", "bar_date": sig["date"]}
    return None


def evaluate_exit(symbol, position, bars, p, realtime_price):
    """
    规则一（保护性止损）+ 规则二（第2次反转离场）。
    position: {entry_price, stop, entry_date, ...}
    返回 EXIT 信号 dict 或 None。
    """
    if not position:
        return None
    stop = position.get("stop")
    # 规则一：保护性止损触发
    if stop is not None and realtime_price <= stop:
        return {"type": "EXIT", "symbol": symbol, "reason": "STOP", "rule": "R1"}
    # 规则二：连续 N 根看跌反转K线 -> 离场
    n = int(p["exit_reversal_bars"])
    if len(bars) >= n and ind.consecutive_reversals(bars, n):
        return {"type": "EXIT", "symbol": symbol, "reason": "REVERSAL", "rule": "R2"}
    return None
