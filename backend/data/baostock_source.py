"""baostock 适配层：A股历史日K（带复权因子），作为腾讯/新浪日K 的质量补充。

baostock 提供后复权/前复权/不复权日K，以及换手率、PE 等字段，数据质量高，
但为盘后历史数据（非实时），且单请求约 0.3s、不支持并发，因此仅用于
「监控范围 + 持仓」等小名单的日K 精修，不参与全市场实时扫描。

代码映射：本系统 A股代码形如 sh600519 / sz000001 -> baostock 需要 sh.600519 / sz.000001。
"""
from __future__ import annotations

import time
import threading
from typing import Optional

import baostock as bs

_LOCK = threading.Lock()
_LOGGED_IN = False


def _ensure_login() -> bool:
    """线程安全地确保已登录 baostock（登录一次复用）。"""
    global _LOGGED_IN
    if _LOGGED_IN:
        return True
    with _LOCK:
        if _LOGGED_IN:
            return True
        try:
            lg = bs.login()
            if lg.error_code == "0":
                _LOGGED_IN = True
                return True
        except Exception:
            pass
        return False


def to_bs_code(symbol: str) -> Optional[str]:
    """sh600519 -> sh.600519；非法返回 None。"""
    s = symbol.lower()
    if s.startswith("sh"):
        return "sh." + s[2:]
    if s.startswith("sz"):
        return "sz." + s[2:]
    return None


def fetch_daily_k(symbol: str, start_date: str = "2020-01-01",
                  end_date: str = "2050-12-31", adjust: str = "3") -> list:
    """取单只 A股日K。

    adjust: "1"=后复权 "2"=前复权 "3"=不复权
    返回 list[dict]: date, open, high, low, close, volume, amount, turnover, peTTM
    失败返回 []。
    """
    bs_code = to_bs_code(symbol)
    if not bs_code:
        return []
    if not _ensure_login():
        return []
    fields = "date,open,high,low,close,volume,amount,turn,peTTM"
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, fields, start_date=start_date, end_date=end_date,
            frequency="d", adjustflag=adjust)
        rows = []
        while rs.error_code == "0" and rs.next():
            r = rs.get_row_data()
            try:
                rows.append({
                    "date": r[0],
                    "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]),
                    "volume": float(r[5]) if r[5] else 0.0,
                    "amount": float(r[6]) if r[6] else 0.0,
                    "turnover": float(r[7]) if r[7] else 0.0,
                    "peTTM": float(r[8]) if r[8] else None,
                })
            except (ValueError, IndexError):
                continue
        return rows
    except Exception:
        return []


def fetch_daily_k_batch(symbols: list, start_date: str = "2020-01-01",
                        adjust: str = "3") -> dict:
    """批量取日K，返回 {symbol: [bars]}。小名单使用。"""
    out = {}
    for sym in symbols:
        bars = fetch_daily_k(sym, start_date=start_date, adjust=adjust)
        if bars:
            out[sym] = bars
        time.sleep(0.05)  # baostock 轻量限速，避免封禁
    return out


def logout() -> None:
    global _LOGGED_IN
    if _LOGGED_IN:
        try:
            bs.logout()
        except Exception:
            pass
        _LOGGED_IN = False
