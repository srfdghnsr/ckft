# -*- coding: utf-8 -*-
"""验证：A股主板过滤、商品期货乘数、策略在真实K线上的回放。"""
import sys, datetime
sys.path.insert(0, ".")
from backend.data import symbols as sym
from backend.config import multiplier_for, FUTURE_MULTIPLIER, INIT_CAPITAL, DEFAULT_PARAMS
from backend.data import kline as kmod
from backend.engine import strategy as strat
from backend.engine import matcher as match
from backend.accounts import account as acct

print("=== 1) A股主板过滤 is_main_board ===")
checks = [("sh601398",True),("sz000001",True),("sz002594",True),("sh688001",False),
          ("sz300750",False),("sz301012",False),("bj830799",False),("sh600519",True),
          ("sz000651",True),("sh900901",False)]
allok = True
for code, exp in checks:
    got = sym.is_main_board(code)
    flag = "OK" if got==exp else "FAIL"
    if got!=exp: allok=False
    print(f"  {flag} {code} -> {got} (期望 {exp})")

print("\n=== 2) 商品期货乘数 multiplier_for ===")
for s in ["hf_bu2611","hf_ma2611","hf_rb2611","hf_fg2611","hf_sa2611","hf_sm2611","hf_sf2611","hf_c2611","hf_cs2611"]:
    print(f"  {s} -> {multiplier_for(s)}")

print("\n=== 3) 策略回放（真实K线，日线级）===")
params = dict(DEFAULT_PARAMS)
astock_list, future_list = sym.load_watchlist()
print(f"  watchlist: A股{len(astock_list)} 期货{len(future_list)}")

a_acc = acct.Account("A股", False, INIT_CAPITAL)
f_acc = acct.Account("期货", True, INIT_CAPITAL)
klines = {}
for s in astock_list + future_list:
    try:
        b = kmod.fetch_kline(s, 240)
        if b: klines[s] = b
    except Exception as e:
        print("  kline err", s, e)
print(f"  klines loaded: {len(klines)}")

# 简化回放：逐根K线评估信号并撮合
price_map = {}
signals = []
for s in astock_list + future_list:
    bars = klines.get(s)
    if not bars or len(bars) < params["breakout_n"]+2: continue
    acc = f_acc if s.lower().startswith(("nf","hf")) else a_acc
    for i in range(params["breakout_n"]+2, len(bars)):
        win = bars[:i+1]
        last_date = win[-1]["date"]
        t = last_date + " 14:30:00"; today = last_date
        px = win[-1]["close"]
        price_map[s] = px
        if s in acc.positions:
            sig = strat.evaluate_exit(s, acc.positions[s], win, params, px)
            if sig:
                res = match.execute_exit(acc, sig, px, params, t, today, price_map)
                signals.append((today,s,res)); 
        else:
            sig = strat.evaluate_entry(s, win, params, False, True, True, False)
            if sig:
                res = match.execute_entry(acc, sig, px, params, t, {}, price_map)
                signals.append((today,s,res))

print(f"  总信号/成交: {len(signals)}")
entries = [x for x in signals if x[2].get('signal')=='ENTRY' and x[2].get('ok')]
exits   = [x for x in signals if x[2].get('signal')=='EXIT' and x[2].get('ok')]
print(f"  成功入场: {len(entries)}  成功出场: {len(exits)}")
print(f"  期货最终权益: {f_acc.equity(price_map):.2f} (起始 {INIT_CAPITAL})")
print(f"  A股最终权益: {a_acc.equity(price_map):.2f} (起始 {INIT_CAPITAL})")
print("  样本成交:")
for d,s,res in signals[:8]:
    print(f"    {d} {s} {res.get('signal')} ok={res.get('ok')} px={res.get('price')} qty={res.get('qty')} rule={res.get('rule')} reason={res.get('reason')}")
print("\nALL FILTERS OK" if allok else "\nFILTER CHECK FAILED")
