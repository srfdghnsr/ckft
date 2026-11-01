# -*- coding: utf-8 -*-
"""
指标计算：服务六条交易规则。
- 强势信号K线（规则一）：涨幅、收在高位、量比
- 突破（规则一）：收盘价创近 N 日新高
- 保护性止损（规则一）：百分比止损 与 ATR 止损取较保守者
- 连续反转K线（规则二）：连续 N 根阴线 -> 离场
所有函数对“当日成形K线”也适用（bars[-1] 为最新一根）。
"""


def _prev_close(bars, idx=-1):
    if len(bars) >= 2 and idx == -1:
        return bars[-2]["close"]
    return bars[idx]["close"]


def is_strong_bar(sig, bars, p):
    """规则一：强势信号K线。收涨幅、收在高位、量比 三条件同时满足。"""
    try:
        prev_close = bars[-2]["close"] if len(bars) >= 2 else sig["open"]
    except (KeyError, IndexError):
        prev_close = sig["open"]
    if prev_close <= 0:
        prev_close = sig["open"]
    gain = (sig["close"] - prev_close) / prev_close * 100.0

    # 1) 收盘涨幅 >= strong_gain_pct
    if gain < float(p["strong_gain_pct"]):
        return False
    # 2) 收在高位：close >= high * strong_close_ratio
    if sig["high"] <= 0 or sig["close"] < sig["high"] * float(p["strong_close_ratio"]):
        return False
    # 3) 量比 >= strong_vol_ratio（量 / 近20日均量）
    vol = sig.get("volume", 0.0) or 0.0
    if vol <= 0:
        return False
    n = 20
    hist = [b.get("volume", 0.0) or 0.0 for b in bars[-(n + 1):-1]]
    avg_vol = sum(hist) / len(hist) if hist else 0.0
    if avg_vol <= 0:
        return False
    vol_ratio = vol / avg_vol
    if vol_ratio < float(p["strong_vol_ratio"]):
        return False
    return True


def is_breakout(sig, bars, p):
    """规则一：收盘价创近 N 日新高（不含当根）。"""
    n = int(p["breakout_n"])
    window = [b["high"] for b in bars[-(n + 1):-1]]
    if not window:
        return False
    return sig["close"] > max(window)


def _atr(bars, period):
    """简易 True Range 均值（ATR）。"""
    period = int(period)
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(len(bars) - 1, max(0, len(bars) - period - 1), -1):
        cur, prev = bars[i], bars[i - 1]
        tr = max(cur["high"] - cur["low"],
                 abs(cur["high"] - prev["close"]),
                 abs(cur["low"] - prev["close"]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def protective_stop(entry_ref, sig, bars, p):
    """规则一：保护性止损。百分比止损 与 ATR 止损取较保守者（更靠近入场 = 更小风险）。"""
    pct = float(p["stop_loss_pct"]) / 100.0
    stop_pct = sig["low"] * (1.0 - pct)  # 信号K线最低价下方 pct%
    atr = _atr(bars, int(p["atr_period"]))
    stop_atr = entry_ref - atr * float(p["atr_stop_mult"])
    # 取两者中较高者（更保守）；且必须低于入场价（多头止损）
    stop = max(stop_pct, stop_atr)
    if stop >= entry_ref:
        stop = sig["low"] * (1.0 - pct)
    return round(stop, 4)


def consecutive_reversals(bars, n):
    """规则二：连续 N 根反转（阴）K线 -> 离场。"""
    n = int(n)
    if len(bars) < n:
        return False
    last = bars[-n:]
    return all(b["close"] < b["open"] for b in last)
