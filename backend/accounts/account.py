# -*- coding: utf-8 -*-
"""
双账户与持仓管理。
- A股账户（is_future=False）：T+1、整手、涨跌停限制、手续费按金额。
- 期货账户（is_future=True）：T+0、保证金、合约乘数、手续费按手。
权益计算：
  A股  equity = cash + Σ qty*price
  期货  equity = cash + Σ qty*mult*(price-entry)   （开仓时已扣保证金，平仓返还）
"""
from backend.config import multiplier_for


class Account:
    def __init__(self, name, is_future, init_capital):
        self.name = name
        self.is_future = is_future
        self.init_capital = init_capital
        self.cash = init_capital
        self.positions = {}   # symbol -> position dict
        self.trades = []      # 成交记录
        self.realized = 0.0   # 累计已实现盈亏

    # ---------- 下单 ----------
    def can_buy(self, symbol, qty, price, fee, margin_pct, max_positions):
        if qty <= 0:
            return False, "数量无效"
        if len(self.positions) >= max_positions:
            return False, "达到最大持仓数"
        if self.is_future:
            mult = multiplier_for(symbol)
            margin = qty * mult * price * margin_pct
            if margin > self.cash:
                return False, "保证金不足"
        else:
            cost = qty * price + fee
            if cost > self.cash:
                return False, "现金不足"
        return True, ""

    def buy(self, symbol, qty, price, fee, margin_pct=0.10, ts=None):
        if self.is_future:
            mult = multiplier_for(symbol)
            margin = qty * mult * price * margin_pct
            self.cash -= margin
            self.positions[symbol] = {
                "symbol": symbol, "qty": qty, "entry_price": price,
                "entry_date": (ts or "")[:10], "entry_time": ts or "",
                "side": "LONG", "multiplier": mult, "margin": margin,
                "entry_fee": fee, "stop": None,
            }
        else:
            self.cash -= (qty * price + fee)
            self.positions[symbol] = {
                "symbol": symbol, "qty": qty, "entry_price": price,
                "entry_date": (ts or "")[:10], "entry_time": ts or "",
                "side": "LONG", "entry_fee": fee, "stop": None,
            }
        self.trades.append({
            "time": ts, "symbol": symbol, "side": "BUY", "price": price,
            "qty": qty, "fee": fee, "rule": "",
        })
        return self.positions[symbol]

    def sell(self, symbol, qty, price, fee, ts=None):
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0, False
        qty = min(qty, pos["qty"])
        entry_fee = pos.get("entry_fee", 0.0)
        if self.is_future:
            mult = pos["multiplier"]
            unreal = qty * mult * (price - pos["entry_price"])
            self.cash += pos["margin"] * (qty / pos["qty"]) + unreal
            pnl = unreal - entry_fee - fee
        else:
            pnl = qty * (price - pos["entry_price"]) - entry_fee - fee
            self.cash += qty * price - fee
        pos["qty"] -= qty
        if pos["qty"] <= 0:
            del self.positions[symbol]
        self.realized += pnl
        self.trades.append({
            "time": ts, "symbol": symbol, "side": "SELL", "price": price,
            "qty": qty, "fee": fee, "pnl": round(pnl, 2), "rule": "",
        })
        return pnl, True

    # ---------- 估值 ----------
    def position_value(self, symbol, price):
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        if self.is_future:
            return pos["qty"] * pos["multiplier"] * (price - pos["entry_price"])
        return pos["qty"] * price

    def market_value(self, price_map):
        mv = 0.0
        for sym, pos in self.positions.items():
            px = price_map.get(sym)
            if px is None:
                px = pos["entry_price"]
            if self.is_future:
                mv += pos["qty"] * pos["multiplier"] * (px - pos["entry_price"])
            else:
                mv += pos["qty"] * px
        return mv

    def equity(self, price_map):
        return self.cash + self.market_value(price_map)

    def floating_pnl(self, price_map):
        return self.market_value(price_map)

    def snapshot(self, price_map):
        eq = self.equity(price_map)
        return {
            "name": self.name,
            "is_future": self.is_future,
            "cash": round(self.cash, 2),
            "equity": round(eq, 2),
            "market_value": round(self.market_value(price_map), 2),
            "realized": round(self.realized, 2),
            "init_capital": self.init_capital,
            "return_pct": round((eq - self.init_capital) / self.init_capital * 100, 2),
            "positions": [
                {
                    "symbol": s, "qty": p["qty"], "entry_price": p["entry_price"],
                    "stop": p.get("stop"), "entry_date": p.get("entry_date"),
                    "multiplier": p.get("multiplier"),
                    "float_pnl": round(self.position_value(s, price_map.get(s, p["entry_price"])), 2),
                }
                for s, p in self.positions.items()
            ],
        }
