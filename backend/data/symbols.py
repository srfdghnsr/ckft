# -*- coding: utf-8 -*-
"""
候选池 / 监控范围 配置与筛选逻辑。

概念区分：
- 监控范围（scope）：引擎实时扫描的标的集合，用户可在前端编辑（A股 + 期货）。
  默认种子仅作初始样本；真正的“候选池覆盖范围”由准入函数 is_candidate_eligible 决定。
- 候选池（candidate pool）：信号驱动。只有触发交易信号（evaluate_entry 命中）的标的
  才会被纳入，外加当前持仓。见 scheduler.scan / scheduler.get_dashboard。

A股候选池准入范围（覆盖范围）：
- 主板：沪市 sh60 开头、深市 000/001/002 开头。
- 场内基金（ETF/LOF）：上交所 5xxxxx、深交所 15xxxx / 16xxxx。
- 天然剔除 科创板(688)、创业板(300/301)、北交所(8开头)。

期货：仅 9 个商品品种（见 ALLOWED_FUTURE_PRODUCTS）。
"""
from backend.config import DATA_DIR
import os, json, time

try:
    import requests
except Exception:  # requests 始终可用（依赖已装），此处仅为静态容错
    requests = None

# 默认监控范围（种子）：主板蓝筹 + 代表性场内基金（ETF）。
# 仅初始运行样本；候选池覆盖范围实际由 is_candidate_eligible 决定（含全部主板+ETF）。
ASTOCK_SEED = [
    "sh601398",  # 工商银行
    "sh601288",  # 农业银行
    "sz000001",  # 平安银行
    "sh600028",  # 中国石化
    "sz000725",  # 京东方A
    "sh600900",  # 长江电力
    "sh601012",  # 隆基绿能
    "sh600036",  # 招商银行
    "sh601318",  # 中国平安
    "sh600276",  # 恒瑞医药
    "sh600519",  # 贵州茅台（高价，1万买不起整手→自动跳过，仅观察）
    "sh601939",  # 建设银行
    "sh600887",  # 伊利股份
    "sz000651",  # 格力电器
    # 场内基金（ETF）示例，验证准入逻辑包含 ETF
    "sh510300",  # 沪深300ETF（上交所）
    "sz159919",  # 沪深300ETF（深交所）
]

FUTURE_WATCHLIST = [
    "hf_bu2611",  # 沥青（上期所）
    "hf_ma2611",  # 甲醇（郑商所）
    "hf_rb2611",  # 螺纹钢（上期所）
    "hf_fg2611",  # 玻璃（郑商所）
    "hf_sa2611",  # 纯碱（郑商所）
    "hf_sm2611",  # 锰硅（郑商所）
    "hf_sf2611",  # 硅铁（郑商所）
    "hf_c2611",   # 玉米（大商所）
    "hf_cs2611",  # 玉米淀粉（大商所）
]

WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlist.json")
UNIVERSE_PATH = os.path.join(DATA_DIR, "universe.json")

# 期货仅允许以下 9 个商品品种（按用户约束）
ALLOWED_FUTURE_PRODUCTS = {"bu", "ma", "rb", "fg", "sa", "sm", "sf", "c", "cs"}

# 期货品种中文名（品种前缀 -> 中文，键统一小写）。用于行情表/扫描/持仓的中文展示。
FUTURE_PRODUCT_CN = {
    "bu": "沥青", "ma": "甲醇", "rb": "螺纹钢", "fg": "玻璃", "sa": "纯碱",
    "sm": "锰硅", "sf": "硅铁", "c": "玉米", "cs": "玉米淀粉",
    # 兼容历史/其它品种（若用户增删），键统一小写
    "if": "沪深300股指", "ih": "上证50股指", "ic": "中证500股指", "im": "中证1000股指",
    "tf": "五年国债", "ts": "两年国债", "au": "黄金", "ag": "白银",
    "cu": "沪铜", "ru": "橡胶",
}


def future_display_name(symbol: str) -> str:
    """期货中文名：品种中文 + 合约月。例：hf_c2611 -> 玉米2611。"""
    core = symbol.split("_")[-1]
    prod = ""
    for ch in core:
        if ch.isalpha():
            prod += ch
        else:
            break
    month = core[len(prod):]
    cn = FUTURE_PRODUCT_CN.get(prod.lower())
    return (cn + month) if cn else symbol


# ---------------- A股准入（覆盖范围）判定 ----------------

def is_main_board(code: str) -> bool:
    """A股主板：沪市 60 开头、深市 000/001/002 开头。
    剔除 科创板(688)、创业板(300/301)、北交所(8 开头)。"""
    c = code.lower()
    if not (c.startswith("sh") or c.startswith("sz")):
        return False
    num = c[2:]
    if len(num) != 6 or not num.isdigit():
        return False
    if c.startswith("sh"):
        return num.startswith("60")
    if c.startswith("sz"):
        return num[:3] in ("000", "001", "002")
    return False


def is_etf(code: str) -> bool:
    """场内基金（ETF/LOF）：上交所 5xxxxx、深交所 15xxxx / 16xxxx。"""
    c = code.lower()
    if not (c.startswith("sh") or c.startswith("sz")):
        return False
    num = c[2:]
    if len(num) != 6 or not num.isdigit():
        return False
    if c.startswith("sh"):
        return num.startswith("5")          # 上交所 ETF/LOF：510~519 等
    if c.startswith("sz"):
        return num[:2] in ("15", "16")      # 深交所 ETF(159) / LOF(16x)
    return False


def is_candidate_eligible(code: str) -> bool:
    """候选池准入：A股主板 或 场内基金（ETF/LOF）。
    即“覆盖范围 = 除科创板/创业板/北交所外的全部可交易A股 + 场内基金”。"""
    return is_main_board(code) or is_etf(code)


def is_allowed_future(symbol: str) -> bool:
    """期货仅允许 9 个商品品种。"""
    core = symbol.split("_")[-1].lower()
    prod = ""
    for ch in core:
        if ch.isalpha():
            prod += ch
        else:
            break
    return prod in ALLOWED_FUTURE_PRODUCTS


# ---------------- 监控范围（用户可编辑的扫描集合） ----------------

def load_watchlist():
    """载入用户监控范围（A股 + 期货），强制用准入函数过滤。"""
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                a = [s for s in d.get("astock", ASTOCK_SEED) if is_candidate_eligible(s)]
                fl = [s for s in d.get("future", FUTURE_WATCHLIST) if is_allowed_future(s)]
                return a, fl
        except Exception:
            pass
    return ([s for s in ASTOCK_SEED if is_candidate_eligible(s)],
            [s for s in FUTURE_WATCHLIST if is_allowed_future(s)])


def save_watchlist(astock, future):
    """保存监控范围，强制剔除不合格标的（非主板A股/非允许期货）。"""
    a = [s for s in astock if is_candidate_eligible(s)]     # 仅主板A股 + 场内基金
    f = [s for s in future if is_allowed_future(s)]         # 仅 9 个商品期货
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as fl:
        json.dump({"astock": a, "future": f}, fl, ensure_ascii=False, indent=2)
    return a, f


# ---------------- 全市场候选池范围（自动发现） ----------------

def load_universe():
    if os.path.exists(UNIVERSE_PATH):
        try:
            with open(UNIVERSE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d.get("codes", [])
        except Exception:
            pass
    return []


def save_universe(codes):
    with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump({"codes": codes, "built_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=2)


def build_astock_universe(force: bool = False):
    """构建全市场 A股（主板）+ 场内基金 代码清单，缓存到 universe.json。
    优先用东方财富列表接口（一次请求）；失败则：force 时用“区间生成+行情校验”自包含构建，
    否则回退到内置种子。返回已用 is_candidate_eligible 过滤的合格代码列表。
    说明：若东方财富不可达且非强制刷新，回退到种子（覆盖范围为种子样本）；
    可在前端点击“刷新全市场范围”（force）触发自包含全量构建。"""
    # 命中缓存且未强制刷新：直接复用（7 天内）
    if not force and os.path.exists(UNIVERSE_PATH):
        age = time.time() - os.path.getmtime(UNIVERSE_PATH)
        if age < 7 * 86400:
            cached = load_universe()
            if cached:
                return cached
    codes = _fetch_universe_eastmoney()
    if codes:
        save_universe(codes)
        return codes
    if force:
        # 东方财富不可达：用区间生成 + 腾讯行情校验，自包含构建全量合格标的
        gen = _generate_universe_ranges()
        if gen:
            save_universe(gen)
            return gen
    # 回退：种子
    return [s for s in ASTOCK_SEED if is_candidate_eligible(s)]


def _fetch_universe_eastmoney():
    """东方财富行情列表：全部A股 + 场内基金。返回合格代码（sh/sz 前缀）。"""
    if requests is None:
        return []
    try:
        # m:0=沪 m:1=深；t:6/t:2=A股，t:13=基金（ETF/LOF），t:80/t:23 为补充
        fs = "m:0+t:6,m:1+t:2,m:0+t:80,m:1+t:23,m:0+t:13,m:1+t:13"
        url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10000"
               f"&fs={fs}&fields=f12,f13&_={int(time.time() * 1000)}")
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0",
                                  "Referer": "https://quote.eastmoney.com/"})
        r.raise_for_status()
        j = r.json()
        items = (j.get("data") or {}).get("diff") or []
        codes = []
        for it in items:
            c = it.get("f12")
            m = it.get("f13")
            if not c:
                continue
            sym = ("sh" if m == 1 else "sz") + str(c).lower()
            if is_candidate_eligible(sym):
                codes.append(sym)
        return codes
    except Exception:
        return []


def future_display_name_safe(symbol: str) -> str:
    return future_display_name(symbol)


# ---------------- 自包含全量构建（东方财富不可达时的回退） ----------------

def _candidate_code_pool():
    """按代码区间生成“主板 + 场内基金”候选代码（含大量未上市占位，需行情校验剔除）。"""
    pools = []
    # 沪市主板 600 / 601 / 603 / 605
    for p in ("600", "601", "603", "605"):
        for i in range(1000):
            pools.append(f"sh{p}{i:03d}")
    # 深市主板 000 / 001 / 002
    for p in ("000", "001", "002"):
        for i in range(1000):
            pools.append(f"sz{p}{i:03d}")
    # 沪市场内基金（ETF/LOF）：510~519
    for p in ("510", "511", "512", "513", "515", "516", "518", "519"):
        for i in range(1000):
            pools.append(f"sh{p}{i:03d}")
    # 深市 ETF(159) / LOF(160~169)
    for p in ("159", "160", "161", "162", "163", "164", "165", "166", "167", "168", "169"):
        for i in range(1000):
            pools.append(f"sz{p}{i:03d}")
    return pools


def _generate_universe_ranges():
    """用腾讯行情逐批校验候选代码，保留真实存在且合格的标的。无需东方财富。
    注意：为一次性构建（~数百次请求），仅建议在前端“刷新全市场范围”时触发。"""
    from backend.data import quotes as qmod
    codes = _candidate_code_pool()
    valid = []
    for i in range(0, len(codes), 80):
        batch = codes[i:i + 80]
        try:
            out = qmod.fetch_quotes(batch)
            for s, q in out.items():
                if q.get("ok") and is_candidate_eligible(s):
                    valid.append(s)
        except Exception:
            continue
    return valid
