# -*- coding: utf-8 -*-
"""把看板数据导出为静态站点（供 GitHub Pages 托管）。

产物：
- docs/index.html  : 自包含单文件（内联 CSS/数据，无外部依赖），每 5 分钟自动刷新
- docs/data.json   : 原始看板数据快照，便于程序化取用

设计原则：服务端渲染（Python 直接拼 HTML），不依赖浏览器端框架，
避免静态托管环境下的接口/CORS 问题。
"""
from __future__ import annotations

import html
import json
import os

# ---------------- 格式化助手 ----------------

def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _num(v, nd: int = 2, dash: str = "—") -> str:
    if v is None or v == "":
        return dash
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return dash


def _pct(v, nd: int = 2, dash: str = "—") -> str:
    if v is None or v == "":
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return dash
    return f"{f:+.{nd}f}%"


def _cls(v) -> str:
    """涨红跌绿（A股习惯）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "muted"
    if f > 0:
        return "up"
    if f < 0:
        return "down"
    return "muted"


def _src_tag(src: str) -> str:
    if src == "kline":
        return '<span class="tag tag-day">日线</span>'
    if src == "akshare":
        return '<span class="tag tag-alt">akshare</span>'
    return ""


# ---------------- 权益曲线 ----------------

def _equity_svg(hist, w: int = 960, h: int = 190) -> str:
    pts = []
    for e in hist or []:
        try:
            pts.append(float(e.get("astock", 0)) + float(e.get("future", 0)))
        except (TypeError, ValueError):
            continue
    if len(pts) < 2:
        return '<div class="empty">暂无权益曲线：需在交易时段运行后逐点累积</div>'

    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or max(abs(hi) * 0.01, 1.0)
    pad = 10
    n = len(pts)
    coords = []
    for i, v in enumerate(pts):
        x = pad + (w - 2 * pad) * i / (n - 1)
        y = pad + (h - 2 * pad) * (1 - (v - lo) / rng)
        coords.append((x, y))

    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"{coords[0][0]:.1f},{h - pad} {poly} {coords[-1][0]:.1f},{h - pad}"
    color = "#ff4d4f" if pts[-1] >= pts[0] else "#1fb85b"
    return (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="eqsvg">'
        f'<polygon points="{area}" fill="{color}" opacity="0.12"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.6"/>'
        f'</svg>'
        f'<div class="eqmeta">区间 {_num(lo)} ~ {_num(hi)} ｜ 最新 {_num(pts[-1])} ｜ 采样 {n} 点</div>'
    )


# ---------------- 各面板 ----------------

def _account_cards(d: dict) -> str:
    cards = []
    for key, label in (("astock", "A股账户"), ("future", "期货账户")):
        a = (d.get("accounts") or {}).get(key) or {}
        rp = a.get("return_pct")
        cards.append(
            f'<div class="card">'
            f'<h2>{label}<span class="hint">{_esc("T+1 · 整手" if key == "astock" else "T+0 · 保证金")}</span></h2>'
            f'<div class="kpi">'
            f'<div class="item"><div class="label">总权益</div>'
            f'<div class="val {_cls(rp)}">{_num(a.get("equity"))}</div></div>'
            f'<div class="item"><div class="label">累计收益率</div>'
            f'<div class="val {_cls(rp)}">{_pct(rp)}</div></div>'
            f'</div>'
            f'<div class="kv">'
            f'<span>现金 <b>{_num(a.get("cash"))}</b></span>'
            f'<span>持仓市值 <b>{_num(a.get("market_value"))}</b></span>'
            f'<span>已实现 <b class="{_cls(a.get("realized"))}">{_num(a.get("realized"))}</b></span>'
            f'<span>初始 <b>{_num(a.get("init_capital"), 0)}</b></span>'
            f'</div></div>'
        )
    return "".join(cards)


def _candidate_table(d: dict) -> str:
    rows = d.get("candidates") or []
    if not rows:
        return '<div class="empty">当前无候选：候选池只收录「已触发交易信号」的标的</div>'
    price_map = {q.get("symbol"): q.get("price") for q in (d.get("quotes") or [])}
    trs = []
    for c in rows:
        px = c.get("price")
        if px is None:
            px = price_map.get(c.get("symbol"))
        state = c.get("state") or ""
        tag = "tag-hold" if state == "持有" else "tag-cand"
        rule = ("R" + str(c.get("rule"))) if c.get("rule") else "—"
        trs.append(
            f'<tr><td><span class="tag {tag}">{_esc(state)}</span></td>'
            f'<td class="l">{_esc(c.get("symbol"))}</td>'
            f'<td class="l">{_esc(c.get("name"))}</td>'
            f'<td>{_esc(rule)}</td>'
            f'<td>{_num(c.get("entry"))}</td>'
            f'<td>{_num(c.get("stop"))}</td>'
            f'<td>{_num(px)}</td></tr>'
        )
    return (
        '<table><thead><tr><th class="l">状态</th><th class="l">代码</th><th class="l">名称</th>'
        '<th>规则</th><th>入场参考</th><th>止损</th><th>现价</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
    )


def _position_table(d: dict) -> str:
    price_map = {q.get("symbol"): q.get("price") for q in (d.get("quotes") or [])}
    name_map = {q.get("symbol"): q.get("name") for q in (d.get("quotes") or [])}
    trs = []
    for key, label in (("astock", "A股"), ("future", "期货")):
        for p in ((d.get("accounts") or {}).get(key) or {}).get("positions") or []:
            sym = p.get("symbol")
            px = price_map.get(sym)
            pnl = p.get("float_pnl")
            trs.append(
                f'<tr><td class="l">{label}</td>'
                f'<td class="l">{_esc(sym)}</td>'
                f'<td class="l">{_esc(name_map.get(sym) or "")}</td>'
                f'<td>{_num(p.get("qty"), 2)}</td>'
                f'<td>{_num(p.get("entry_price"))}</td>'
                f'<td>{_num(px)}</td>'
                f'<td>{_num(p.get("stop"))}</td>'
                f'<td class="{_cls(pnl)}">{_num(pnl)}</td>'
                f'<td>{_esc(p.get("entry_date") or "—")}</td></tr>'
            )
    if not trs:
        return '<div class="empty">当前无持仓</div>'
    return (
        '<table><thead><tr><th class="l">账户</th><th class="l">代码</th><th class="l">名称</th>'
        '<th>数量</th><th>成本</th><th>现价</th><th>止损</th><th>浮动盈亏</th><th>建仓日</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
    )


def _quote_table(d: dict) -> str:
    rows = d.get("quotes") or []
    if not rows:
        return '<div class="empty">暂无行情</div>'
    trs = []
    for q in rows:
        sym = q.get("symbol") or ""
        chg = q.get("change_pct")
        pos = ' <span class="tag tag-hold">持仓</span>' if q.get("has_position") else ""
        trs.append(
            f'<tr><td class="l">{_esc(sym)}</td>'
            f'<td class="l">{_esc(q.get("name"))}{pos}</td>'
            f'<td>{_num(q.get("price"))}</td>'
            f'<td class="{_cls(chg)}">{_pct(chg)}</td>'
            f'<td>{_num(q.get("prevclose"))}</td>'
            f'<td class="l">{_src_tag(q.get("price_source"))}</td></tr>'
        )
    return (
        '<table><thead><tr><th class="l">代码</th><th class="l">名称</th>'
        '<th>最新价</th><th>涨跌幅</th><th>昨收</th><th class="l">来源</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
    )


def _signal_table(d: dict) -> str:
    rows = d.get("signals") or []
    if not rows:
        return '<div class="empty">暂无信号记录</div>'
    trs = []
    for s in rows[:40]:
        side = s.get("side") or s.get("action") or ""
        cls = "up" if ("买" in str(side) or "buy" in str(side).lower()) else "down"
        trs.append(
            f'<tr><td class="l">{_esc(s.get("time") or s.get("t") or "")}</td>'
            f'<td class="l">{_esc(s.get("symbol"))}</td>'
            f'<td class="l {cls}">{_esc(side)}</td>'
            f'<td>{_num(s.get("price"))}</td>'
            f'<td class="l">{_esc(s.get("reason") or s.get("msg") or s.get("rule") or "")}</td></tr>'
        )
    return (
        '<table><thead><tr><th class="l">时间</th><th class="l">代码</th>'
        '<th class="l">方向</th><th>价格</th><th class="l">说明</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
    )


# ---------------- 样式 ----------------

CSS = """
:root{
  --bg:#0e1116; --panel:#161b22; --panel2:#1c232c; --border:#2a313c;
  --text:#e6edf3; --muted:#8b97a6; --accent:#3b82f6;
  --up:#ff4d4f; --down:#1fb85b; --warn:#f0a020;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;
     font-size:13px;line-height:1.5;-webkit-font-smoothing:antialiased}
.header{display:flex;align-items:center;gap:12px;padding:12px 18px;background:var(--panel);
        border-bottom:1px solid var(--border);flex-wrap:wrap}
.header h1{font-size:17px;font-weight:600}
.badge{background:#3a1d1d;color:var(--up);border:1px solid #5a2a2a;padding:2px 9px;
       border-radius:4px;font-size:11px;font-weight:600}
.status{margin-left:auto;color:var(--muted);font-size:12px;text-align:right}
.status b{color:var(--text);font-weight:600}
.live{color:var(--down)} .closed{color:var(--warn)}
.wrap{padding:12px;display:flex;flex-direction:column;gap:12px;max-width:1400px;margin:0 auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px}
.card h2{font-size:13px;color:var(--muted);font-weight:600;margin-bottom:10px;
         display:flex;align-items:center;gap:8px}
.hint{color:#5f6b7a;font-size:11px;font-weight:400}
.kpi{display:flex;gap:18px;flex-wrap:wrap}
.kpi .item{flex:1;min-width:110px}
.kpi .label{color:var(--muted);font-size:11px}
.kpi .val{font-size:20px;font-weight:700;margin-top:2px}
.kv{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:11.5px}
.kv b{color:var(--text);font-weight:600}
.up{color:var(--up)} .down{color:var(--down)} .muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--border);white-space:nowrap}
th{color:var(--muted);font-weight:500}
td.l,th.l{text-align:left}
tbody tr:hover{background:var(--panel2)}
.scroll{max-height:340px;overflow:auto}
.tag{padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}
.tag-cand{background:#3a1d1d;color:var(--up)}
.tag-hold{background:#1d3a2a;color:var(--down)}
.tag-day{background:#2a2413;color:var(--warn)}
.tag-alt{background:#1b2b3a;color:#5aa8f0}
.empty{color:var(--muted);font-size:12px;padding:14px 4px;text-align:center}
.eqsvg{width:100%;height:190px;display:block}
.eqmeta{color:var(--muted);font-size:11px;margin-top:6px}
.warnbox{background:#2a2113;border:1px solid #5a4420;color:var(--warn);
         padding:8px 12px;border-radius:6px;font-size:11.5px;line-height:1.6}
.footer{color:var(--muted);font-size:11px;padding:4px 12px 24px;text-align:center;line-height:1.8}
.footer a{color:var(--accent);text-decoration:none}
"""


# ---------------- 主入口 ----------------

def build_html(d: dict, repo_url: str = "") -> str:
    last = d.get("last_update") or "—"
    if d.get("market_open"):
        st = '<span class="live">● 交易时段</span>'
    else:
        st = '<span class="closed">● 休市</span>'
    mode = d.get("scan_mode")
    mode_txt = "全市场扫描" if mode == "full" else "仅监控范围"
    univ = d.get("universe_count")
    meta = f'{_esc(mode_txt)} ｜ 覆盖 {_esc(univ)} 个合格标的' if mode == "full" else _esc(mode_txt)

    scope = d.get("scope") or {}
    a_n = len(scope.get("astock") or [])
    f_n = len(scope.get("future") or [])

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>模拟交易看板 · A股 + 期货</title>
<style>{CSS}</style>
</head>
<body>
<div class="header">
  <h1>模拟交易看板</h1>
  <span class="badge">模拟盘 · 非真实交易</span>
  <span class="hint">A股 主板+场内基金 ｜ 期货 9 商品</span>
  <div class="status">
    {st}<br>
    数据时间 <b>{_esc(last)}</b>（UTC+8）<br>
    {meta}
  </div>
</div>

<div class="wrap">
  <div class="warnbox">
    数据来源：A股实时/日K 走腾讯行情，期货走新浪（商品期货无逐笔实时源，价格取日线最后一根，标注「日线」）。
    本页由 GitHub Actions 定时任务自动更新，每 5 分钟自动刷新；成交为模拟撮合，不涉及真实资金。
  </div>

  <div class="grid2">
    {_account_cards(d)}
  </div>

  <div class="card">
    <h2>权益曲线<span class="hint">A股 + 期货 合计</span></h2>
    {_equity_svg(d.get("equity_history"))}
  </div>

  <div class="card">
    <h2>候选池<span class="hint">仅收录已触发交易信号的标的 + 当前持仓</span></h2>
    <div class="scroll">{_candidate_table(d)}</div>
  </div>

  <div class="card">
    <h2>持仓<span class="hint">模拟撮合</span></h2>
    <div class="scroll">{_position_table(d)}</div>
  </div>

  <div class="card">
    <h2>实时行情<span class="hint">监控范围 {a_n} 只 A股 + {f_n} 个期货</span></h2>
    <div class="scroll">{_quote_table(d)}</div>
  </div>

  <div class="card">
    <h2>最近信号</h2>
    <div class="scroll">{_signal_table(d)}</div>
  </div>
</div>

<div class="footer">
  模拟交易系统 · 行情真实、成交模拟 ｜ 由 GitHub Actions 每 10 分钟（交易时段）自动运行一轮
  {'｜ <a href="' + _esc(repo_url) + '">源码仓库</a>' if repo_url else ''}
</div>
</body>
</html>"""
    return body


def write(d: dict, outdir: str, repo_url: str = "") -> str:
    """写出 docs/index.html 与 docs/data.json，返回 index.html 路径。"""
    os.makedirs(outdir, exist_ok=True)
    html_path = os.path.join(outdir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(d, repo_url=repo_url))
    with open(os.path.join(outdir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return html_path
