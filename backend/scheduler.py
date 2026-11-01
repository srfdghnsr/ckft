# -*- coding: utf-8 -*-
"""
模拟交易引擎：行情刷新、策略信号、自动撮合、状态聚合。
- 监控范围（scope）：用户配置实时扫描的标的（A股 + 期货）。
- 候选池（candidate pool）：信号驱动。只有触发交易信号（evaluate_entry 命中）的标的
  才会被纳入，外加当前持仓。覆盖范围 = 主板A股 + 场内基金（见 symbols.is_candidate_eligible）。
- 全市场扫描（full_market_scan）：将 A股 扫描范围从“监控范围”扩展到“全市场合格标的”，
  通过批量行情预筛（涨跌幅阈值）限制日线详评数量，兼顾覆盖范围与性能。
"""
import time
import datetime
from backend.config import (DEFAULT_PARAMS, INIT_CAPITAL, POLL_INTERVAL,
                            KLINE_REFRESH_INTERVAL, STATE_PATH)
from backend.data import symbols as symdata
from backend.data import quotes as qmod
from backend.data import kline as kmod
# 备用数据源（可选依赖）：导入失败不应拖垮主链路（腾讯/新浪）
try:
    from backend.data import akshare_source as aksrc
except Exception:
    aksrc = None
try:
    from backend.data import baostock_source as bssrc
except Exception:
    bssrc = None
from backend.engine import strategy as strat
from backend.engine import matcher as match
from backend.accounts import account as acct
from backend.accounts import store as st


class SimEngine:
    def __init__(self):
        self.params = st.load_params(DEFAULT_PARAMS)
        self.astock_list, self.future_list = symdata.load_watchlist()  # 监控范围（用户可编辑）
        self.universe = symdata.build_astock_universe()                # 全市场合格 A股（主板+ETF）
        self.accounts = {
            "astock": acct.Account("A股账户", False, INIT_CAPITAL),
            "future": acct.Account("期货账户", True, INIT_CAPITAL),
        }
        self.klines = {}        # symbol -> [bars]
        self.quotes = {}        # symbol -> quote dict
        self.prevclose = {}     # symbol -> 昨收
        self.cooldowns = {}     # symbol -> 剩余冷却K线数
        self.last_bar_date = {} # symbol -> 最近K线日期
        self.equity_history = []  # [{t, astock, future}]
        self.signals_log = []     # 最近信号
        self.last_update = ""
        self.market_open = False
        self._last_kline_ts = 0
        self._state_loaded = False
        self._last_rollover_date = ""
        self.active_movers = []   # 全市场模式下的活跃预筛标的
        self._load_state()

    # ---------------- 持久化 ----------------
    def _load_state(self):
        s = st.load_state(STATE_PATH)
        if not s:
            return
        try:
            for key in ("astock", "future"):
                a = s.get("accounts", {}).get(key)
                if a:
                    acc = self.accounts[key]
                    acc.cash = a["cash"]; acc.realized = a["realized"]
                    acc.positions = a.get("positions", {})
                    acc.trades = a.get("trades", [])
            self.cooldowns = s.get("cooldowns", {})
            self.equity_history = s.get("equity_history", [])[-5000:]
            self.last_bar_date = s.get("last_bar_date", {})
            self._state_loaded = True
        except Exception:
            pass

    def _save_state(self):
        data = {
            "accounts": {k: {"cash": a.cash, "realized": a.realized,
                             "positions": a.positions, "trades": a.trades[-500:]}
                         for k, a in self.accounts.items()},
            "cooldowns": self.cooldowns,
            "equity_history": self.equity_history[-5000:],
            "last_bar_date": self.last_bar_date,
        }
        st.save_state(data, STATE_PATH)

    # ---------------- 范围/集合 ----------------
    def refresh_universe(self):
        """重建全市场合格 A股 范围（强制刷新）。"""
        self.universe = symdata.build_astock_universe(force=True)
        return len(self.universe)

    def _compute_active_scope(self):
        """全市场扫描开启且范围已就绪时，A股扫描集合 = 全市场；否则 = 监控范围。"""
        if self.params.get("full_market_scan") and self.universe:
            self.active_astock = self.universe
        else:
            self.active_astock = self.astock_list

    def _scan_set(self):
        """当前需要评估信号的标的集合。
        全市场模式：活跃预筛标的 + 监控范围 + 持仓 + 期货（监控范围始终全量扫描）。
        监控范围模式：监控范围 + 期货。"""
        if self.params.get("full_market_scan") and getattr(self, "active_movers", None):
            s = (set(self.active_movers)
                 | set(self.astock_list)
                 | set(self.accounts["astock"].positions)
                 | set(self.future_list))
        else:
            s = set(self.astock_list) | set(self.future_list)
        return list(s)

    # ---------------- 行情 ----------------
    def refresh_klines(self):
        # 全市场模式：对“活跃预筛标的 + 监控范围 + 持仓 + 期货”拉日线，控制请求量
        if self.params.get("full_market_scan") and getattr(self, "active_movers", None):
            targets = (list(self.active_movers)
                       + list(self.astock_list)
                       + list(self.accounts["astock"].positions)
                       + list(self.accounts["future"].positions)
                       + self.future_list)
        else:
            targets = self.astock_list + self.future_list
        targets = list(dict.fromkeys(targets))  # 去重保序
        for sym in targets:
            try:
                bars = kmod.fetch_kline(sym, 240)
                # 主源（腾讯）日K 为空时，回退 baostock -> akshare 新浪源，提升日K 鲁棒性
                if not bars and bssrc is not None:
                    bars = bssrc.fetch_daily_k(sym, adjust="3")
                if not bars and aksrc is not None:
                    bars = aksrc.fetch_daily_k_akshare(sym)
                if bars:
                    self.klines[sym] = bars
                    self.prevclose[sym] = bars[-1]["close"]
                    self.last_bar_date[sym] = bars[-1]["date"]
            except Exception:
                pass

    def refresh_quotes(self):
        if self.params.get("full_market_scan") and self.universe:
            self._refresh_quotes_full()
        else:
            self._refresh_quotes_scope()

    def _refresh_quotes_scope(self):
        """监控范围模式：行情全量刷新（原有行为）。"""
        all_syms = self.astock_list + self.future_list
        qs = qmod.fetch_quotes(all_syms)
        self.quotes = {}
        for sym, q in qs.items():
            self.quotes[sym] = q
            if sym.lower().startswith(("nf", "hf")):
                q["name"] = symdata.future_display_name(sym)   # 期货统一中文名（例：玉米2611）
            if q.get("ok"):
                self._merge_quote_to_kline(sym, q)
            else:
                # 期货实时：新浪对商品期货常返回空 -> 回退到日线最后一根（盘中更新）作为当前价
                self._fallback_kline_price(sym, q)
                self._apply_akshare_fallback(sym, q)   # A股主源失败时回退 akshare

    def _refresh_quotes_full(self):
        """全市场模式：监控范围始终全量；额外全市场标的按涨跌幅阈值预筛，控制详评数量。"""
        thr = float(self.params.get("scan_move_threshold", 3.0))
        univ = self.universe
        scope_set = set(self.astock_list)   # 用户配置范围：始终扫描，不被预筛剔除
        extra = [s for s in univ if s not in scope_set]
        allq = qmod.fetch_quotes(univ + self.future_list)
        holdings = (list(self.accounts["astock"].positions)
                    + list(self.accounts["future"].positions))
        movers = [s for s, q in allq.items()
                  if s in set(extra) and q.get("ok") and abs(q.get("change_pct", 0)) >= thr]
        # 上限：按涨跌幅绝对值取前 N，避免命中过多导致日线详评/请求量失控（CI 单轮时限）
        cap = int(self.params.get("max_movers", 150) or 0)
        if cap > 0 and len(movers) > cap:
            movers.sort(key=lambda s: abs(allq[s].get("change_pct", 0)), reverse=True)
            movers = movers[:cap]
        keep = set(movers) | scope_set | set(holdings) | set(self.future_list)
        self.active_movers = movers
        self.quotes = {}
        for sym in keep:
            q = allq.get(sym)
            if q is None:
                q = {"symbol": sym, "ok": False}
            self.quotes[sym] = q
            if sym.lower().startswith(("nf", "hf")):
                q["name"] = symdata.future_display_name(sym)
            if q.get("ok"):
                self._merge_quote_to_kline(sym, q)
            else:
                self._fallback_kline_price(sym, q)
                self._apply_akshare_fallback(sym, q)   # A股主源失败时回退 akshare

    def _refresh_quotes_hot(self):
        """全市场模式非日线刷新 tick：仅轻量刷新持仓 + 期货行情，保证 P&L 实时。"""
        hot = (list(self.accounts["future"].positions)
               + list(self.accounts["astock"].positions)
               + self.future_list)
        hot = list(dict.fromkeys(hot))
        qs = qmod.fetch_quotes(hot)
        for sym, q in qs.items():
            self.quotes[sym] = q
            if sym.lower().startswith(("nf", "hf")):
                q["name"] = symdata.future_display_name(sym)
            if q.get("ok"):
                self._merge_quote_to_kline(sym, q)
            else:
                self._fallback_kline_price(sym, q)
                self._apply_akshare_fallback(sym, q)   # A股主源失败时回退 akshare

    def _fallback_kline_price(self, sym, q):
        """商品期货无逐笔实时时，用日线最后一根（成形K线，盘中更新）作为当前价。"""
        bars = self.klines.get(sym)
        if not bars:
            q["ok"] = False
            return
        last = bars[-1]
        prev = bars[-2]["close"] if len(bars) >= 2 else last["close"]
        q["ok"] = True
        q["name"] = q.get("name") or sym
        q["price"] = last["close"]
        q["open"] = last["open"]
        q["high"] = last["high"]
        q["low"] = last["low"]
        q["prevclose"] = prev
        q["volume"] = last["volume"]
        q["time"] = last["date"]
        q["change_pct"] = (last["close"] - prev) / prev * 100 if prev else 0.0
        q["price_source"] = "kline"   # 标注：日线价（非逐笔实时）

    def _merge_quote_to_kline(self, sym, q):
        """用实时数据更新当日成形K线（高/低/收/量），用于日内止损与P&L。"""
        bars = self.klines.get(sym)
        if not bars:
            return
        last = bars[-1]
        px = q.get("price")
        if not px:
            return
        last["close"] = px
        last["high"] = max(last["high"], px, q.get("high", px))
        last["low"] = min(last["low"], px, q.get("low", px))
        if q.get("volume"):
            last["volume"] = q["volume"]
        # 昨收
        if q.get("prevclose"):
            self.prevclose[sym] = q["prevclose"]

    def _apply_akshare_fallback(self, sym, q):
        """A股实时主源（腾讯）失败时，回退到 akshare 新浪实时快照（带会话缓存）。
        仅对 A股生效；期货实时仍由新浪主源处理。"""
        if q.get("ok"):
            return
        if not sym.lower().startswith(("sh", "sz")):
            return
        if aksrc is None:
            return
        try:
            aq = aksrc.get_realtime_quote_akshare(sym)
        except Exception:
            aq = None
        if aq and aq.get("price"):
            q["ok"] = True
            q["name"] = aq.get("name") or q.get("name") or sym
            q["price"] = aq["price"]
            q["prevclose"] = aq.get("prevclose")
            q["open"] = aq.get("open")
            q["high"] = aq.get("high")
            q["low"] = aq.get("low")
            q["change_pct"] = aq.get("change_pct")
            q["volume"] = aq.get("volume")
            q["price_source"] = "akshare"
            self._merge_quote_to_kline(sym, q)

    def daily_k_from(self, symbol, source="tencent"):
        """取日K，source 可选：tencent（默认）/ baostock / akshare。
        baostock 提供带复权的历史日K；akshare 提供新浪历史日K。"""
        if source == "baostock":
            bars = bssrc.fetch_daily_k(symbol, adjust="3") if bssrc is not None else []
        elif source == "akshare":
            bars = aksrc.fetch_daily_k_akshare(symbol, adjust="") if aksrc is not None else []
        else:
            bars = kmod.fetch_kline(symbol, 240)
        return bars

    # ---------------- 时段/事件 ----------------
    def _time_ok(self):
        now = time.localtime()
        if not qmod.is_market_open(now):
            return True
        mins = now.tm_hour * 60 + now.tm_min
        buf = int(self.params["open_buffer_min"])
        cbuf = int(self.params["close_buffer_min"])
        if 570 <= mins <= 690:       # 上午
            if mins < 570 + buf or mins > 690 - cbuf:
                return False
        elif 780 <= mins <= 900:     # 下午
            if mins < 780 + buf or mins > 900 - cbuf:
                return False
        return True

    def _event_ok(self, today):
        if not self.params.get("event_blacklist_enabled"):
            return True
        return today not in (self.params.get("event_blacklist") or [])

    # ---------------- 主循环 ----------------
    def tick(self):
        now = time.localtime()
        self.market_open = qmod.is_market_open(now)
        t = time.strftime("%Y-%m-%d %H:%M:%S", now)
        self.last_update = t
        today = t[:10]

        self._compute_active_scope()

        if self.params.get("full_market_scan") and self.universe:
            # 全市场模式：宽口径预筛按 K线间隔；持仓/期货每 tick 轻刷
            if time.time() - self._last_kline_ts > KLINE_REFRESH_INTERVAL:
                self._refresh_quotes_full()
                self.refresh_klines()
                self._last_kline_ts = time.time()
            else:
                self._refresh_quotes_hot()
        else:
            # 监控范围模式：行情每 tick；K线按间隔（原有行为）
            self._refresh_quotes_scope()
            if time.time() - self._last_kline_ts > KLINE_REFRESH_INTERVAL:
                self.refresh_klines()
                self._last_kline_ts = time.time()

        if self.market_open:
            self._process_signals(t)
            self._record_equity(t)

        # 合约到期滚动：每个自然日检查一次
        if today != self._last_rollover_date:
            self._rollover_futures(today)
            self._last_rollover_date = today

        self._save_state()

    # ---------------- 期货合约滚动 ----------------
    @staticmethod
    def _next_month_code(yymm: int) -> int:
        yy, mm = yymm // 100, yymm % 100
        mm += 1
        if mm > 12:
            mm = 1; yy += 1
        return yy * 100 + mm

    def _rollover_futures(self, today):
        """当前活跃合约最后交易日距今>10天时，切换到更新的活跃月份（有持仓则跳过）。"""
        new_future = list(self.future_list)
        changed = False
        for i, sym in enumerate(self.future_list):
            if sym in self.accounts["future"].positions:
                continue  # 有持仓不滚动，等平仓
            core = sym.split("_")[-1]
            prod = ""
            for ch in core:
                if ch.isalpha():
                    prod += ch
                else:
                    break
            try:
                cur_m = int(core[len(prod):])
            except ValueError:
                continue
            bars = self.klines.get(sym)
            if not bars:
                continue
            last_d = bars[-1]["date"]
            try:
                last_dt = datetime.date.fromisoformat(last_d)
                if (datetime.date.today() - last_dt).days <= 10:
                    continue  # 未到期
            except ValueError:
                continue
            best_m = cur_m
            best_d = last_d
            cand_m = cur_m
            for _ in range(1, 8):
                cand_m = self._next_month_code(cand_m)
                cand_sym = f"hf_{prod}{cand_m}"
                try:
                    cbars = kmod.fetch_kline(cand_sym, 3)
                except Exception:
                    cbars = []
                if cbars and cbars[-1]["date"] > best_d:
                    best_d = cbars[-1]["date"]; best_m = cand_m
            if best_m != cur_m:
                new_future[i] = f"hf_{prod}{best_m}"
                changed = True
        if changed:
            self.set_watchlist(self.astock_list, new_future)

    def _process_signals(self, t):
        today = t[:10]
        time_ok = self._time_ok()
        event_ok = self._event_ok(today)
        price_map = {s: q.get("price") for s, q in self.quotes.items() if q.get("ok")}
        for sym in self._scan_set():
            bars = self.klines.get(sym)
            if not bars or len(bars) < int(self.params["breakout_n"]) + 2:
                continue
            # 新日 -> 冷却递减
            if self.last_bar_date.get(sym) != bars[-1]["date"]:
                self.last_bar_date[sym] = bars[-1]["date"]
                if self.cooldowns.get(sym, 0) > 0:
                    self.cooldowns[sym] = max(0, self.cooldowns[sym] - 1)
            acc_key = "future" if sym.lower().startswith(("nf", "hf")) else "astock"
            acc = self.accounts[acc_key]
            has_pos = sym in acc.positions
            cd_active = self.cooldowns.get(sym, 0) > 0

            # 出场优先
            if has_pos:
                sig = strat.evaluate_exit(sym, acc.positions[sym], bars, self.params,
                                         price_map.get(sym, acc.positions[sym]["entry_price"]))
                if sig:
                    res = match.execute_exit(acc, sig, price_map.get(sym, acc.positions[sym]["entry_price"]),
                                             self.params, t, today, price_map)
                    self._log_signal(t, sym, res)
                    if res.get("ok"):
                        self.cooldowns[sym] = int(self.params["cooldown_bars"])  # 规则五
                continue

            # 入场
            sig = strat.evaluate_entry(sym, bars, self.params, cd_active, time_ok, event_ok, has_pos)
            if sig:
                res = match.execute_entry(acc, sig, price_map.get(sym, sig["entry_ref"]),
                                          self.params, t, self.prevclose, price_map)
                self._log_signal(t, sym, res)

    def _log_signal(self, t, sym, res):
        entry = {
            "time": t, "symbol": sym, "type": res.get("signal"),
            "side": "BUY" if res.get("signal") == "ENTRY" else "SELL",
            "price": res.get("price"), "qty": res.get("qty"),
            "rule": res.get("rule"), "reason": res.get("reason"),
            "ok": res.get("ok"), "pnl": res.get("pnl"),
        }
        self.signals_log.append(entry)
        if len(self.signals_log) > 300:
            self.signals_log = self.signals_log[-300:]

    def _record_equity(self, t):
        price_map = {s: q.get("price") for s, q in self.quotes.items() if q.get("ok")}
        eq_a = self.accounts["astock"].equity(price_map)
        eq_f = self.accounts["future"].equity(price_map)
        self.equity_history.append({"t": t, "astock": round(eq_a, 2), "future": round(eq_f, 2)})
        if len(self.equity_history) > 6000:
            self.equity_history = self.equity_history[-6000:]

    # ---------------- 候选池（信号驱动） ----------------
    def scan(self):
        """候选池：在当前日线上评估入场候选 / 持仓状态。
        只有触发交易信号（evaluate_entry 命中）的标的才会进入候选池（state=候选），
        外加当前持仓（state=持有）。返回列表按信号驱动，非手工名单。"""
        mode = "full" if (self.params.get("full_market_scan") and self.universe) else "scope"
        out = []
        for sym in self._scan_set():
            bars = self.klines.get(sym)
            if not bars or len(bars) < int(self.params["breakout_n"]) + 2:
                continue
            q = self.quotes.get(sym, {})
            name = q.get("name", sym)
            acc_key = "future" if sym.lower().startswith(("nf", "hf")) else "astock"
            has_pos = sym in self.accounts[acc_key].positions
            if has_pos:
                pos = self.accounts[acc_key].positions[sym]
                px = q.get("price") or pos["entry_price"]
                out.append({"symbol": sym, "name": name, "state": "持有", "scope": mode,
                            "entry": pos["entry_price"], "stop": pos.get("stop"),
                            "price": px, "rule": ""})
            else:
                # 入池条件：必须触发交易信号
                sig = strat.evaluate_entry(sym, bars, self.params, False, True, True, False)
                if sig:
                    out.append({"symbol": sym, "name": name, "state": "候选", "scope": mode,
                                "entry": sig["entry_ref"], "stop": sig["stop"],
                                "price": q.get("price"), "rule": sig["rule"]})
        return out

    def get_dashboard(self):
        price_map = {s: q.get("price") for s, q in self.quotes.items() if q.get("ok")}
        a_snap = self.accounts["astock"].snapshot(price_map)
        f_snap = self.accounts["future"].snapshot(price_map)
        # 实时行情表：仅展示“监控范围 + 持仓 + 期货”（用户关注集），避免全市场活跃标的淹没面板。
        # 全市场信号命中另见“候选池”面板。
        monitored = list(dict.fromkeys(
            self.astock_list + self.future_list
            + list(self.accounts["astock"].positions)
            + list(self.accounts["future"].positions)))
        quote_rows = []
        for sym in monitored:
            q = self.quotes.get(sym, {})
            bars = self.klines.get(sym, [])
            has_pos = (sym in self.accounts["astock"].positions) or (sym in self.accounts["future"].positions)
            quote_rows.append({
                "symbol": sym, "name": q.get("name", sym), "price": q.get("price"),
                "prevclose": q.get("prevclose"), "change_pct": q.get("change_pct"),
                "volume": q.get("volume"), "ok": q.get("ok", False),
                "price_source": q.get("price_source", "realtime"),
                "has_position": has_pos, "bars": len(bars),
            })
        full = bool(self.params.get("full_market_scan") and self.universe)
        return {
            "last_update": self.last_update,
            "market_open": self.market_open,
            "scan_mode": "full" if full else "scope",
            "universe_count": len(self.universe) if full else len(self.astock_list),
            "accounts": {"astock": a_snap, "future": f_snap},
            "quotes": quote_rows,
            "signals": list(reversed(self.signals_log[-60:])),
            "candidates": self.scan(),   # 候选池（信号驱动）
            "equity_history": self.equity_history[-600:],
            "params": self.params,
            "scope": {"astock": self.astock_list, "future": self.future_list},  # 监控范围（用户可编辑）
        }

    # ---------------- 控制接口 ----------------
    def set_params(self, new_params):
        self.params.update(new_params)
        # 事件黑名单：文本输入 -> 列表
        eb = self.params.get("event_blacklist")
        if isinstance(eb, str):
            self.params["event_blacklist"] = [x.strip() for x in eb.split(",") if x.strip()]
        st.save_params(self.params)
        return self.params

    def set_watchlist(self, astock, future):
        self.astock_list, _ = symdata.save_watchlist(astock, future)
        # 重新载入：save_watchlist 已强制剔除不合格 A股/期货，确保内存与持久化一致
        self.astock_list, self.future_list = symdata.load_watchlist()
        self.refresh_klines()
        return True

    def manual_reset(self):
        self.accounts = {
            "astock": acct.Account("A股账户", False, INIT_CAPITAL),
            "future": acct.Account("期货账户", True, INIT_CAPITAL),
        }
        self.cooldowns = {}; self.equity_history = []; self.signals_log = []
        self._save_state()
        return True
