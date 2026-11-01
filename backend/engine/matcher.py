# -*- coding: utf-8 -*-
"""
模拟撮合：把策略信号落地为账户成交，应用 T+1/涨跌停/手续费/仓位上限。
所有成交为模拟，非真实下单。
"""
from backend.config import limit_pct_for_astock


def _apply_slippage(price, pct, is_buy):
    f = pct / 100.0
    return price * (1 + f) if is_buy else price * (1 - f)


def execute_entry(account, signal, realtime_price, params, ts, prevclose_map, price_map):
    sym = signal["symbol"]
    entry = _apply_slippage(realtime_price, params["slippage_pct"], True)
    stop = signal["stop"]

    # A股涨跌停不成交
    if not account.is_future:
        pc = prevclose_map.get(sym)
        if pc and pc > 0:
            lp = limit_pct_for_astock(sym)
            limit_up = pc * (1 + lp)
            if entry >= limit_up * 0.999:
                return {"ok": False, "symbol": sym, "reason": "涨停无法买入", "signal": "ENTRY"}

    equity = account.equity(price_map)
    max_pos = (params["max_positions_future"] if account.is_future
               else params["max_positions_astock"])
    risk_amt = equity * (params["risk_per_trade_pct"] / 100.0)

    if account.is_future:
        from backend.config import multiplier_for
        mult = account.positions.get(sym, {}).get("multiplier") or multiplier_for(sym)
        per_risk = (entry - stop) * mult if (entry - stop) > 0 else 0
        if per_risk <= 0:
            return {"ok": False, "symbol": sym, "reason": "止损无效(>=入场)", "signal": "ENTRY"}
        # 期货：按 R 风险计算“分数合约”（模拟账户，真实为整手；¥1万不足1手保证金，
        # 故以分数合约建模，清晰标注）。保证金 = 合约数×乘数×价×保证金率 须 <= 现金。
        qty = risk_amt / per_risk
        qty = round(qty, 4)
        margin_pct = params["future_margin_pct"]
        fee = params["future_fee_per_lot"] * qty
        margin = qty * mult * entry * margin_pct
        if margin > account.cash:
            return {"ok": False, "symbol": sym, "reason": "保证金不足", "signal": "ENTRY"}
    else:
        per_risk = (entry - stop)
        if per_risk <= 0:
            return {"ok": False, "symbol": sym, "reason": "止损无效(>=入场)", "signal": "ENTRY"}
        # A股：整手(100股)。R 风险目标下，价格较高时不足1手 -> 至少1手（否则无法交易），
        # 现金不足以买1手则跳过（真实：1万买不起高价股）。
        shares_ideal = int(risk_amt // per_risk)
        lots_ideal = shares_ideal // 100
        lots = max(1, lots_ideal)
        cash_lots = int(account.cash // (entry * 100)) if entry > 0 else 0
        lots = min(lots, cash_lots)
        qty = lots * 100
        fee = entry * qty * params["astock_fee_pct"]
        margin_pct = 0.0

    if qty <= 0:
        return {"ok": False, "symbol": sym, "reason": "资金不足/不足1手", "signal": "ENTRY"}

    ok, why = account.can_buy(sym, qty, entry, fee, margin_pct, max_pos)
    if not ok:
        return {"ok": False, "symbol": sym, "reason": why, "signal": "ENTRY"}

    pos = account.buy(sym, qty, entry, fee, margin_pct, ts)
    pos["stop"] = stop
    # 记录规则到最后一笔成交
    if account.trades:
        account.trades[-1]["rule"] = signal.get("rule", "")
        account.trades[-1]["stop"] = round(stop, 3)
    return {"ok": True, "symbol": sym, "qty": qty, "price": round(entry, 3),
            "stop": round(stop, 3), "rule": signal.get("rule", ""), "signal": "ENTRY"}


def execute_exit(account, signal, realtime_price, params, ts, today, price_map):
    sym = signal["symbol"]
    pos = account.positions.get(sym)
    if not pos:
        return {"ok": False, "symbol": sym, "reason": "无持仓", "signal": "EXIT"}
    # A股 T+1：当日买入不可当日卖出
    if not account.is_future and pos.get("entry_date") == today:
        return {"ok": False, "symbol": sym, "reason": "T+1当日不可卖", "signal": "EXIT"}
    exit_px = _apply_slippage(realtime_price, params["slippage_pct"], False)
    if account.is_future:
        fee = params["future_fee_per_lot"] * pos["qty"]
    else:
        fee = exit_px * pos["qty"] * params["astock_fee_pct"]
    pnl, done = account.sell(sym, pos["qty"], exit_px, fee, ts)
    if account.trades:
        account.trades[-1]["rule"] = signal.get("rule", "")
    return {"ok": done, "symbol": sym, "price": round(exit_px, 3),
            "pnl": round(pnl, 2), "reason": signal.get("reason", ""), "rule": signal.get("rule", ""), "signal": "EXIT"}
