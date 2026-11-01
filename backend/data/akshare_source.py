"""akshare 适配层：A股实时/日K 的备用数据源（新浪源）。

说明（实测，2026-11-01）：
- akshare 的东方财富实时接口（*_spot_em）在本环境被代理拦截，不可用。
- 新浪源接口可用：
  * stock_zh_a_spot      -> 全市场实时快照（~5576 只，约 12s/70 页，慢，故做会话缓存）
  * stock_zh_a_daily     -> 新浪历史日K（不带复权，质量尚可）
本模块定位为「腾讯 gtimg 失败时的实时回退」+「日K 备用源」，不参与主实时链路。
"""
from __future__ import annotations

import time
import threading
from typing import Optional

import akshare as ak

_SPOT_CACHE: dict = {}          # {code6: quote}
_SPOT_TS: float = 0.0
_SPOT_LOCK = threading.Lock()
_SPOT_MAX_AGE = 60.0            # 缓存 60s，避免每次回退都跑 12s 全市场抓取


def _code6(symbol: str) -> str:
    """sh600519 / sz000001 -> 600519（6 位纯数字代码）。"""
    s = symbol.lower()
    for p in ("sh", "sz"):
        if s.startswith(p):
            return s[2:]
    return s


def fetch_realtime_spot_akshare(force: bool = False) -> dict:
    """取全市场实时快照（新浪），返回 {code6: quote}。

    quote 字段：price, prevclose, open, high, low, change, change_pct, volume, amount, name
    带 60s 会话缓存；force=True 强制重建。失败返回 {}。
    """
    global _SPOT_TS
    now = time.time()
    with _SPOT_LOCK:
        if not force and _SPOT_CACHE and (now - _SPOT_TS) < _SPOT_MAX_AGE:
            return _SPOT_CACHE
    try:
        df = ak.stock_zh_a_spot()
        out = {}
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                raw = str(row.get("代码", "")).strip()
                if not raw:
                    continue
                # akshare 新浪源的代码带交易所前缀（sh600519 / sz000001 / bj920000）；
                # 统一归一为 6 位纯数字作为键，才能被 _code6() 命中。
                low = raw.lower()
                if low.startswith("bj"):
                    continue          # 北交所不在准入范围，跳过
                code = low[2:] if low[:2] in ("sh", "sz") else low
                if not code:
                    continue
                try:
                    out[code] = {
                        "name": str(row.get("名称", "")).strip(),
                        "price": float(row.get("最新价", 0) or 0),
                        "prevclose": float(row.get("昨收", 0) or 0),
                        "open": float(row.get("今开", 0) or 0),
                        "high": float(row.get("最高", 0) or 0),
                        "low": float(row.get("最低", 0) or 0),
                        "change": float(row.get("涨跌额", 0) or 0),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "volume": float(row.get("成交量", 0) or 0),
                        "amount": float(row.get("成交额", 0) or 0),
                    }
                except (ValueError, TypeError):
                    continue
        with _SPOT_LOCK:
            _SPOT_CACHE.clear()
            _SPOT_CACHE.update(out)
            _SPOT_TS = time.time()
        return _SPOT_CACHE
    except Exception:
        # 失败时返回旧缓存（若有），否则空
        with _SPOT_LOCK:
            return dict(_SPOT_CACHE)


def get_realtime_quote_akshare(symbol: str, force: bool = False) -> Optional[dict]:
    """从缓存/实时快照取单只 A股报价（按 6 位代码匹配）。失败返回 None。"""
    cache = fetch_realtime_spot_akshare(force=force)
    return cache.get(_code6(symbol))


def fetch_daily_k_akshare(symbol: str, adjust: str = "") -> list:
    """新浪历史日K（个股用 stock_zh_a_daily；场内基金用 fund_etf_hist_sina）。

    adjust: ""不复权, "qfq"前复权, "hfq"后复权（仅个股支持复权参数）
    返回 list[dict]: date, open, high, low, close, volume, amount
    失败返回 []。
    """
    bs = symbol.lower()
    try:
        from backend.data.symbols import is_etf
        if is_etf(bs):
            # 场内基金（ETF/LOF）：新浪的个股日K 接口不覆盖，改用基金专用接口
            df = ak.fund_etf_hist_sina(symbol=bs)
        else:
            df = ak.stock_zh_a_daily(symbol=bs, adjust=adjust, start_date="19900101")
        if df is None or len(df) == 0:
            return []
        out = []
        for _, r in df.iterrows():
            try:
                out.append({
                    "date": str(r["date"]),
                    "open": float(r["open"]), "high": float(r["high"]),
                    "low": float(r["low"]), "close": float(r["close"]),
                    "volume": float(r["volume"]) if r["volume"] == r["volume"] else 0.0,
                    "amount": float(r.get("amount", 0) or 0),
                })
            except (ValueError, KeyError, TypeError):
                continue
        return out
    except Exception:
        return []
