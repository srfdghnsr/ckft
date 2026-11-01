# -*- coding: utf-8 -*-
"""
实时行情抓取（公共行情 API，无需密钥）。
- A股：腾讯 gtimg（qt.gtimg.cn），GBK 解码。
- 期货：新浪（hq.sinajs.cn，需 Referer），支持 nf_ 金融期货与 hf_ 商品期货。
返回归一化结构：{symbol, name, price, prevclose, open, high, low, change_pct, volume, time, ok}
"""
import re
import time
import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
})
_TIMEOUT = 12

_GTIMG_URL = "https://qt.gtimg.cn/q="
_SINA_URL = "https://hq.sinajs.cn/list="


def _get(url: str) -> str:
    r = _SESSION.get(url, timeout=_TIMEOUT)
    r.raise_for_status()
    # 尝试根据内容推断编码
    return r.content


def parse_gtimg(raw: bytes, symbols):
    """解析腾讯 A股 实时。"""
    text = raw.decode("gbk", errors="replace")
    out = {}
    pat = re.compile(r'v_(\w+)="([^"]*)"')
    for m in pat.finditer(text):
        sym = m.group(1)
        f = m.group(2).split("~")
        try:
            price = float(f[3])
            prevclose = float(f[4])
            open_ = float(f[5])
            # 高/低：取字段33/34与价格/开盘的极值，避免索引歧义
            try:
                hi_cand = float(f[33]); lo_cand = float(f[34])
            except (ValueError, IndexError):
                hi_cand = price; lo_cand = price
            high = max(hi_cand, price, open_)
            low = min(lo_cand, price, open_)
            change_pct = float(f[32]) if len(f) > 32 else 0.0
            # 成交量（手）-> 股
            try:
                vol_lots = float(f[6])
            except (ValueError, IndexError):
                vol_lots = 0.0
            volume = vol_lots * 100.0
            # 时间字段可能为 yyyymmddhhmmss
            tstr = ""
            for token in f:
                if re.fullmatch(r"\d{14}", token):
                    tstr = token
                    break
            out[sym] = {
                "symbol": sym, "name": f[1], "price": price,
                "prevclose": prevclose, "open": open_, "high": high, "low": low,
                "change_pct": change_pct, "volume": volume, "time": tstr, "ok": True,
            }
        except (ValueError, IndexError):
            out[sym] = {"symbol": sym, "ok": False}
    return out


def parse_sina_future(raw: bytes, symbols):
    """解析新浪期货实时。"""
    text = raw.decode("gbk", errors="replace")
    out = {}
    pat = re.compile(r'var hq_str_(\w+)="([^"]*)"')
    for m in pat.finditer(text):
        sym = m.group(1)
        s = m.group(2)
        if not s:
            out[sym] = {"symbol": sym, "ok": False}
            continue
        f = s.split(",")
        try:
            # 字段 0=开 1=高 2=低 3=最新（金融期货连续）
            open_ = float(f[0]); high = float(f[1]); low = float(f[2]); price = float(f[3])
            # 找时间（YYYY-MM-DD）
            tstr = ""
            for i in range(len(f) - 1, -1, -1):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f[i]):
                    tstr = f[i] + " " + (f[i + 1] if i + 1 < len(f) else "")
                    break
            # 昨结算（用于涨跌幅）：在末段寻找第一个合理价格
            prevclose = open_
            for tok in reversed(f):
                try:
                    v = float(tok)
                    if 0 < v < 1e7:
                        prevclose = v
                        break
                except ValueError:
                    continue
            change_pct = (price - prevclose) / prevclose * 100 if prevclose else 0.0
            name = f[-1] if f[-1] else sym
            out[sym] = {
                "symbol": sym, "name": name, "price": price,
                "prevclose": prevclose, "open": open_, "high": high, "low": low,
                "change_pct": change_pct, "volume": 0.0, "time": tstr, "ok": True,
            }
        except (ValueError, IndexError):
            out[sym] = {"symbol": sym, "ok": False}
    return out


def fetch_quotes(symbols: list, chunk: int = 80) -> dict:
    """批量抓取实时行情，按代码前缀路由。A股按 chunk 分批，避免超长 URL / 限流。"""
    result = {}
    a_syms = [s for s in symbols if s.lower().startswith(("sh", "sz"))]
    f_syms = [s for s in symbols if s.lower().startswith(("nf", "hf"))]
    if a_syms:
        for i in range(0, len(a_syms), chunk):
            batch = a_syms[i:i + chunk]
            try:
                raw = _get(_GTIMG_URL + ",".join(batch))
                result.update(parse_gtimg(raw, batch))
            except Exception as e:
                for s in batch:
                    result[s] = {"symbol": s, "ok": False, "error": str(e)}
    if f_syms:
        try:
            raw = _get(_SINA_URL + ",".join(f_syms))
            result.update(parse_sina_future(raw, f_syms))
        except Exception as e:
            for s in f_syms:
                result[s] = {"symbol": s, "ok": False, "error": str(e)}
    # 未返回的标记为不可用
    for s in symbols:
        if s not in result:
            result[s] = {"symbol": s, "ok": False}
    return result


def is_market_open(now=None) -> bool:
    """A股/期货日间交易时段判断（本地时间）。简化：工作日 9:00-15:15 视为可交易。"""
    if now is None:
        now = time.localtime()
    if now.tm_wday >= 5:  # 周末
        return False
    h, m = now.tm_hour, now.tm_min
    # 上午 9:30-11:30，下午 13:00-15:00，期货夜盘/国债略延长至15:15
    minutes = h * 60 + m
    if (9 * 60 + 30 <= minutes <= 11 * 60 + 30) or (13 * 60 <= minutes <= 15 * 60 + 15):
        return True
    return False
