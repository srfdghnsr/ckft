# -*- coding: utf-8 -*-
"""单轮执行器：给 GitHub Actions 等定时环境用（不需要 FastAPI）。

用法：
    python -m cloud.run_once

做的事：
1. 校正时区为 Asia/Shanghai（CI runner 默认 UTC，否则开市判断会错位）
2. 构造引擎（自动加载 data/state.json，恢复历史持仓/权益/冷却）
3. 跑一轮 tick：行情 -> 日线 -> 信号 -> 模拟撮合 -> 合约滚动 -> 落盘
4. 导出静态看板到 docs/（index.html + data.json）

退出码：0 = 正常（含"跑完但有告警"）；1 = 引擎无法初始化（配置/依赖错误）。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _force_beijing_tz() -> None:
    """CI 上强制北京时区，保证 is_market_open / 时间戳口径与实盘一致。

    Windows 无 time.tzset()，跳过（本机时区本就是 UTC+8）。
    """
    if not hasattr(time, "tzset"):
        return
    try:
        off = time.localtime().tm_gmtoff
    except Exception:
        off = None
    if off != 8 * 3600:
        os.environ["TZ"] = "Asia/Shanghai"
        try:
            time.tzset()
        except Exception:
            pass
        print(f"[tz] 已校正时区 -> Asia/Shanghai（原偏移 {off}s）")


def main() -> int:
    _force_beijing_tz()

    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    tzname = time.strftime("%Z", time.localtime())
    print(f"[start] 本地时间 {now} ({tzname})  UTC偏移 {time.localtime().tm_gmtoff}s")

    # 延迟导入：确保时区已校正后再加载引擎（config 可能在导入期读取时间）
    from backend.scheduler import SimEngine
    from cloud import export_static

    try:
        engine = SimEngine()
    except Exception:
        print("[fatal] 引擎初始化失败：")
        traceback.print_exc()
        return 1

    print(f"[init] 监控范围 A股 {len(engine.astock_list)} / 期货 {len(engine.future_list)}；"
          f"全市场合格标的 {len(engine.universe)}；"
          f"max_movers={engine.params.get('max_movers')}")

    rc = 0
    t0 = time.time()
    try:
        engine.tick()
    except Exception:
        rc = 0  # 单轮异常不阻断落盘与页面发布
        print("::warning::本轮 tick 抛异常，已记录并尽力落盘")
        print("[error] tick 异常：")
        traceback.print_exc()
    elapsed = time.time() - t0

    # 尽力落盘（tick 内部已保存一次；异常路径下再保一次）
    try:
        engine._save_state()
    except Exception:
        print("[warn] 状态落盘失败")
        traceback.print_exc()

    # 导出静态看板
    repo_url = os.environ.get("SIMTRADER_REPO_URL", "")
    try:
        out = export_static.write(engine.get_dashboard(), os.path.join(ROOT, "docs"),
                                  repo_url=repo_url)
        print(f"[export] 静态看板已写出 {out}")
    except Exception:
        print("[error] 静态看板导出失败：")
        traceback.print_exc()
        rc = 1

    # 运行摘要（写进 Actions 日志，便于回溯）
    d = engine.get_dashboard()
    a = d["accounts"]["astock"]
    f = d["accounts"]["future"]
    print(f"[done] 耗时 {elapsed:.1f}s ｜ 开市 {d['market_open']} ｜ 模式 {d['scan_mode']}")
    print(f"       A股 权益 {a['equity']} 收益率 {a['return_pct']}% 持仓 {len(a['positions'])}")
    print(f"       期货 权益 {f['equity']} 收益率 {f['return_pct']}% 持仓 {len(f['positions'])}")
    print(f"       行情 {len(d['quotes'])} 行 ｜ 候选池 {len(d['candidates'])} 条 ｜ 信号 {len(d['signals'])} 条")
    return rc


if __name__ == "__main__":
    sys.exit(main())
