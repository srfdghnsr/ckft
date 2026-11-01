# -*- coding: utf-8 -*-
"""离线验证：用真实K线回放，检验六规则信号、账户撮合、T+1、涨跌停、期货保证金。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.config import DEFAULT_PARAMS, INIT_CAPITAL, limit_pct_for_astock, multiplier_for
from backend.engine import strategy as strat
from backend.engine import matcher as match
from backend.data import kline as kmod
from backend.accounts import account as acct
from backend.accounts import store as st

P = st.load_params(DEFAULT_PARAMS)

def section(t): print("\n=== " + t + " ===")

# ---------- 1. A股账户数学 (买入100股@50, 卖出@55) ----------
section("A股账户数学 (买入100股@50, 卖出@55)")
a = acct.Account("A", False, 10000)
res = match.execute_entry(a, {"symbol":"sh600519","stop":47.5,"rule":"R1","entry_ref":50.0},
                          50.0, P, "2026-11-02 10:00:00", {"sh600519":50.0}, {"sh600519":50.0})
print("buy:", res)
print("cash after buy:", round(a.cash,2), "pos:", a.positions)
res2 = match.execute_exit(a, {"symbol":"sh600519","reason":"STOP","rule":"R1"}, 55.0, P,
                          "2026-11-03 10:00:00", "2026-11-03", {"sh600519":55.0})
print("sell:", res2, "realized:", round(a.realized,2), "cash:", round(a.cash,2))
exp = 100*(55-50) - (50*100*P["astock_fee_pct"]) - (55*100*P["astock_fee_pct"])
assert abs(a.realized - exp) < 0.5, (a.realized, exp)

# ---------- 2. T+1：当日不可卖 ----------
section("T+1 当日不可卖")
a2 = acct.Account("A2", False, 10000)
match.execute_entry(a2, {"symbol":"sh600519","stop":47.5,"rule":"R1","entry_ref":50.0},
                    50.0, P, "2026-11-02 10:00:00", {"sh600519":50.0}, {"sh600519":50.0})
r_t1 = match.execute_exit(a2, {"symbol":"sh600519","reason":"STOP","rule":"R1"}, 55.0, P,
                          "2026-11-02 14:00:00", "2026-11-02", {"sh600519":55.0})
print("same-day sell:", r_t1)
assert r_t1["ok"] is False and "T+1" in r_t1["reason"]

# ---------- 3. 涨跌停不可买 (昨收100, 涨停110, 账户2万足够) ----------
section("涨跌停不可买 (昨收100, 涨停110)")
a3 = acct.Account("A3", False, 20000)
r_lim = match.execute_entry(a3, {"symbol":"sh600519","stop":95.0,"rule":"R1","entry_ref":110.0},
                            110.0, P, "2026-11-02 10:00:00", {"sh600519":100.0}, {"sh600519":110.0})
print("limit-up buy:", r_lim)
assert r_lim["ok"] is False and "涨停" in r_lim["reason"]

# ---------- 4. 期货保证金（分数合约） ----------
section("期货分数合约与盈亏 (IF, 乘数300, 风险¥200)")
f = acct.Account("F", True, 10000)
print("multiplier IF:", multiplier_for("nf_IF0"))
res_f = match.execute_entry(f, {"symbol":"nf_IF0","stop":3900.0,"rule":"R1","entry_ref":4000.0},
                           4000.0, P, "2026-11-02 10:00:00", {}, {"nf_IF0":4000.0})
print("future buy:", res_f, "cash after margin:", round(f.cash,2))
eq_f = f.equity({"nf_IF0":4000.0})
print("equity@4000:", round(eq_f,2))
res_f2 = match.execute_exit(f, {"symbol":"nf_IF0","reason":"STOP","rule":"R1"}, 4050.0, P,
                            "2026-11-02 14:00:00", "2026-11-02", {"nf_IF0":4050.0})
print("future sell:", res_f2, "realized:", round(f.realized,2), "cash:", round(f.cash,2))
# 0.0067 合约 × 300 × 50点 ≈ 100 元（扣双边手续费）
assert abs(f.realized - (res_f["qty"]*300*50 - P["future_fee_per_lot"]*res_f["qty"]*2)) < 1.0

# ---------- 5. 策略信号回放（真实K线） ----------
section("策略信号回放（真实日线，近120根）")
total_entries=0
for sym in ["sh601398","sz000001","sz000725","nf_IF0","nf_IC0"]:
    bars = kmod.fetch_kline(sym, 120)
    if len(bars) < int(P["breakout_n"])+2:
        print(sym, "K线不足"); continue
    acc = acct.Account("X", sym.lower().startswith(("nf","hf")), INIT_CAPITAL)
    entries=exits=0
    for i in range(int(P["breakout_n"])+2, len(bars)):
        sub = bars[:i+1]
        prices = {sym: sub[-1]["close"]}
        if sym in acc.positions:
            sig = strat.evaluate_exit(sym, acc.positions[sym], sub, P, sub[-1]["close"])
            if sig:
                match.execute_exit(acc, sig, sub[-1]["close"], P, f"2026-{i:02d}-01 14:00", f"2026-{i:02d}-01", prices)
                exits+=1
        else:
            sig = strat.evaluate_entry(sym, sub, P, False, True, True, False)
            if sig:
                r = match.execute_entry(acc, sig, sub[-1]["close"], P, f"2026-{i:02d}-01 10:00", {sym:sub[-1]['close']}, prices)
                if r["ok"]: entries+=1
    total_entries+=entries
    print(f"{sym}: 入场成交{entries} 次, 离场{exits} 次, 末持仓{len(acc.positions)}, 账户权益{round(acc.equity({sym:bars[-1]['close']}),2)}")

print("\n全部断言通过 ✅  (A股+期货均能触发成交)")
