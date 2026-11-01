# ckft · A股 + 期货 模拟交易看板

用**真实行情数据**驱动、**模拟撮合**的自动化交易看板。双独立账户（A股 ¥10,000 / 期货 ¥10,000），按固定的六条交易规则全自动产生信号并撮合。

> ⚠️ **本项目是模拟盘，不涉及任何真实资金与真实下单。** 所有成交均为本地模拟撮合，仅用于策略验证与学习。

## 在线看板

GitHub Pages 托管自动刷新的静态看板（由 Actions 定时任务产出）：

- **https://srfdghnsr.github.io/ckft/**

## 运行架构

```
GitHub Actions（cron 定时唤醒）
   │  ① 从 state 分支恢复历史持仓/权益/冷却
   │  ② 拉实时行情 → 拉日线 → 评估信号 → 模拟撮合 → 落盘
   │  ③ 把 state 写回 state 分支（单提交，不留历史）
   │  ④ 生成静态看板 → 部署 GitHub Pages
   ▼
https://srfdghnsr.github.io/ckft/   （5 分钟自动刷新）
```

GitHub Actions 的 runner 是一次性的、单 job 最长 6 小时，**无法常驻进程**，因此这里采用「定时唤醒 + 状态持久化」的方案，而不是长驻 Web 服务。本地仍可跑真正的实时 WebSocket 服务（见下）。

**调度（北京时间）**

| 时段 | 频率 |
|---|---|
| 工作日 09:00–15:59（A股 + 期货日盘） | 每 10 分钟 |
| 工作日 21:00–23:59（商品期货夜盘） | 每 10 分钟 |
| 其余时段 | 每小时心跳一次 |
| 周末 | 每 6 小时一次 |

## 可交易范围

- **A股**：仅主板（沪市 60x / 深市 000、001、002），**剔除**科创板 688、创业板 300/301、北交所 8xx/920；**含场内基金**（沪市 5xxxxx，深市 15xxxx / 16xxxx）。
- **期货**：仅 9 个商品品种 —— 沥青 `bu`、甲醇 `ma`、螺纹钢 `rb`、玻璃 `fg`、纯碱 `sa`、锰硅 `sm`、硅铁 `sf`、玉米 `c`、玉米淀粉 `cs`。

以上范围在 `backend/data/symbols.py` 中硬性守卫（`is_main_board` / `is_etf` / `is_candidate_eligible` / `is_allowed_future`），越界标的会被直接拒绝。

## 策略：六条规则

参数集中在 `backend/config.py` 的 `DEFAULT_PARAMS`，全部可调：

1. **强势 K 线 + 突破**：当日涨幅 ≥ `strong_gain_pct`(3%)、量比 ≥ `strong_vol_ratio`(1.5)、收盘突破 `breakout_n`(20) 日高点才考虑入场。
2. **保护性止损**：入场即挂 `stop_loss_pct`(0.5%) 或 `atr_stop_mult`(2) × ATR 的止损。
3. **回踩入场 / 反转离场**：回踩不破 `pullback_tol_pct`(0.5%) 可入场；连续 `exit_reversal_bars`(2) 根阴线离场。
4. **不加仓**：同一标的只允许一笔持仓。
5. **风险仓位 R**：每笔最大风险 = 权益 × `risk_per_trade_pct`(2%)，据此反推数量（A股取整手，期货按保证金 `future_margin_pct`(10%) 折算）。
6. **冷却与时段过滤**：亏损后冷却 `cooldown_bars`(3) 根 K 线；开盘/收盘各 `15` 分钟缓冲不下单；事件黑名单标的跳过。

## 数据源

| 用途 | 主源 | 备用 |
|---|---|---|
| A股实时 + 日K | 腾讯 `qt.gtimg.cn` / `web.ifzq.gtimg.cn` | akshare（新浪）、baostock |
| 期货实时（金融） | 新浪 `hq.sinajs.cn`（`nf_*`） | — |
| 期货日K（商品） | 新浪 `stock2.finance.sina.com.cn` | — |

**已知限制（如实说明）**：商品期货在公开免费源上没有逐笔实时行情，价格取**日线最后一根**（盘中滚动更新），看板上标注为「日线」，非实时 tick。金融期货 `nf_*` 为实时。

## 本地运行（真实时服务）

```bash
pip install -r requirements.txt          # fastapi + uvicorn + requests
python -m backend.main                   # http://127.0.0.1:9528/
```

Windows 可直接双击 `start.bat`。

本地服务带 WebSocket 推送、参数在线调整、K 线查看、监控范围编辑；云端版本只做定时撮合 + 静态快照。

## 目录结构

```
backend/            引擎（策略、撮合、账户、行情、调度）
  config.py         六规则默认参数 + 品种乘数
  scheduler.py      SimEngine：行情刷新 / 信号 / 撮合 / 状态持久化
  data/             行情与标的（腾讯、新浪、akshare、baostock）
  engine/           策略与撮合
  accounts/         账户与状态存取
frontend/           本地实时看板（原生 HTML/JS + Canvas）
cloud/              云端单轮执行器 + 静态看板导出（GitHub Actions 用）
  run_once.py       一次完整 tick（时区校正 → 撮合 → 落盘 → 导出）
  export_static.py  服务端渲染静态站点
.github/workflows/  simtrader.yml：cron 调度 + Pages 发布
```

## 免责声明

本项目仅用于技术研究与策略验证，**不构成任何投资建议**。模拟撮合不包含真实市场的滑点、冲击成本、流动性约束与部分成交，实盘表现必然劣于模拟结果。
