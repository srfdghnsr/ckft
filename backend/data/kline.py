# -*- coding: utf-8 -*-
"""
K线抓取（日线）。用于指标计算与当日成形K线。
- A股：腾讯 web.ifzq.gtimg.cn，返回顺序 [date, open, close, high, low, volume]。
- 期货：新浪 InnerFuturesNewService.getDailyKLine，返回 {d,o,h,l,c,v,...}。
归一化为 [{date, open, high, low, close, volume}, ...]（按时间升序）。
"""
import time
import requests

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

_GTIMG_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,,,{count}"
_SINA_FUT_KLINE = "https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getDailyKLine?symbol={code}"


def fetch_kline_astock(code: str, count: int = 240) -> list:
    url = _GTIMG_KLINE.format(code=code, count=count)
    r = _SESSION.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    node = data.get("data", {}).get(code, {})
    bars = node.get("day") or node.get("qfqday") or []
    out = []
    for b in bars:
        # [date, open, close, high, low, volume]
        out.append({
            "date": b[0],
            "open": float(b[1]),
            "high": float(b[3]),
            "low": float(b[4]),
            "close": float(b[2]),
            "volume": float(b[5]) * 100.0,  # 手 -> 股
        })
    return out


def fetch_kline_future(code: str, count: int = 240) -> list:
    # code 形如 nf_IF0 / hf_RU2601 -> 取纯合约名 IF0 / RU2601
    sym = code.split("_")[-1]
    url = _SINA_FUT_KLINE.format(code=sym)
    r = _SESSION.get(url, timeout=15)
    r.raise_for_status()
    bars = r.json()
    out = []
    for b in bars:
        out.append({
            "date": b["d"],
            "open": float(b["o"]),
            "high": float(b["h"]),
            "low": float(b["l"]),
            "close": float(b["c"]),
            "volume": float(b["v"]),
        })
    return out[-count:] if count else out


def fetch_kline(code: str, count: int = 240) -> list:
    if code.lower().startswith(("sh", "sz")):
        return fetch_kline_astock(code, count)
    else:
        return fetch_kline_future(code, count)
