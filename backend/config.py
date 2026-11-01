# -*- coding: utf-8 -*-
"""
全局配置：路径 + 六条交易规则的可调默认参数。
所有阈值均可在前端参数面板修改并持久化到 data/params.json。
"""
import os

# ---- 路径 ----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # simtrader/
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
for _d in (DATA_DIR,):
    os.makedirs(_d, exist_ok=True)

PARAMS_PATH = os.path.join(DATA_DIR, "params.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# 服务端口
PORT = 9528

# 行情轮询间隔（秒），仅在交易时段内活跃
POLL_INTERVAL = 5
# K线刷新间隔（秒）
KLINE_REFRESH_INTERVAL = 60

# 初始本金（两账户各自）
INIT_CAPITAL = 10000.0

# ---- 六规则默认参数 ----
DEFAULT_PARAMS = {
    # 通用
    "signal_period": "day",          # 信号主周期 day / 5m / 1m
    "full_market_scan": True,        # 全市场扫描：候选池覆盖全部主板A股+场内基金（否则仅监控范围）
    "scan_move_threshold": 3.0,      # 全市场预筛：当日涨跌幅绝对值 >= % 才拉日线详评
    "max_movers": 150,               # 预筛命中上限（按涨跌幅绝对值取前 N），用于约束单轮耗时/请求量
    "risk_per_trade_pct": 2.0,       # R：每笔最大风险占权益比例(%)
    "max_positions_astock": 5,       # A股最大同时持仓
    "max_positions_future": 3,       # 期货最大同时持仓
    "open_buffer_min": 15,           # 开盘后 N 分钟不新开仓
    "close_buffer_min": 15,          # 收盘前 N 分钟不新开仓
    "slippage_pct": 0.0,             # 滑点(%)，默认0

    # 规则一：强势信号K线 + 突破 + 保护性止损
    "strong_gain_pct": 3.0,          # 强势K线：收盘涨幅 >= %
    "strong_close_ratio": 0.96,      # 强势K线：收盘/最高 >= （收在高位）
    "strong_vol_ratio": 1.5,         # 强势K线：量比 >= （成交量/20日均量）
    "breakout_n": 20,                # 突破：收盘价 > 近 N 日最高
    "stop_loss_pct": 0.5,            # 保护性止损：信号K线最低价 - %
    "atr_period": 14,                # ATR 周期
    "atr_stop_mult": 2.0,            # ATR 止损倍数（与百分比止损取较保守者）

    # 规则二：第2入场点 / 第2次反转离场
    "pullback_tol_pct": 0.5,         # 回踩容差：突破位 ± %
    "exit_reversal_bars": 2,         # 离场：连续 N 根反转K线

    # 规则三：不加仓（硬编码，无参数）

    # 规则四：风险&仓位控制
    "astock_fee_pct": 0.00025,        # A股手续费 万2.5（双边）
    "future_fee_per_lot": 5.0,       # 期货手续费 元/手（示例，按品种可覆盖）
    "future_leverage": 10.0,         # 期货杠杆上限（用于保证金占用校验）
    "future_margin_pct": 0.10,       # 期货保证金比例（占合约价值）
    "max_total_risk_pct": 10.0,      # 总风险敞口上限占权益(%)

    # 规则五：亏损后冷却
    "cooldown_bars": 3,              # 止损后冷却 K 根K线

    # 规则六：避开重要事件
    "event_blacklist": [],           # 重大事件日 YYYY-MM-DD 列表（当日不新开仓）
    "event_blacklist_enabled": False,
}

# 期货品种合约乘数（元/吨·手）。key 为品种前缀（小写）。
# 数据来源：上海/大连/郑州商品交易所标准合约。
FUTURE_MULTIPLIER = {
    # 金融期货（若用户后续自行添加）
    "IF": 300.0, "IH": 300.0, "IC": 200.0,
    "TF": 100.0, "TS": 200.0, "IM": 200.0,
    # 商品期货（本项目默认池）
    "BU": 10.0,   # 沥青（上期所）
    "MA": 10.0,   # 甲醇（郑商所）
    "RB": 10.0,   # 螺纹钢（上期所）
    "FG": 20.0,   # 玻璃（郑商所）
    "SA": 20.0,   # 纯碱（郑商所）
    "SM": 5.0,    # 锰硅（郑商所）
    "SF": 5.0,    # 硅铁（郑商所）
    "C": 10.0,    # 玉米（大商所）
    "CS": 10.0,   # 玉米淀粉（大商所）
    "DEFAULT": 10.0,
}

# 期货品种 -> 交易所（用于标注）
FUTURE_EXCHANGE = {
    "BU": "上期所", "RB": "上期所",
    "MA": "郑商所", "FG": "郑商所", "SA": "郑商所", "SM": "郑商所", "SF": "郑商所",
    "C": "大商所", "CS": "大商所",
}

def multiplier_for(symbol: str) -> float:
    """从期货符号（如 nf_IF0 / hf_RU2601）解析品种乘数。"""
    core = symbol.split("_")[-1] if "_" in symbol else symbol  # IF0 / RU2601
    # 取前两位字母作为品种
    prod = ""
    for ch in core:
        if ch.isalpha():
            prod += ch
        else:
            break
    return FUTURE_MULTIPLIER.get(prod, FUTURE_MULTIPLIER["DEFAULT"])

# A股板块涨跌停限制（按代码前缀粗判）
def limit_pct_for_astock(code: str) -> float:
    c = code.upper()
    # 创业板 300/301，科创板 688：±20%
    if c.startswith(("300", "301", "688")):
        return 0.20
    # 北交所 8 开头（京市）：±30%
    if c.startswith("8") and len(c) == 6:
        return 0.30
    # ST：±5%（名称含 ST，调用方判断；此处默认主板10%）
    return 0.10
