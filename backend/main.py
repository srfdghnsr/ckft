# -*- coding: utf-8 -*-
"""FastAPI 入口：静态前端 + REST/WebSocket + 后台行情轮询。"""
import asyncio
import os
import sys
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 确保项目根目录（simtrader/）在 sys.path，便于直接 `python backend/main.py` 启动
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.config import FRONTEND_DIR, PORT, POLL_INTERVAL
from backend.scheduler import SimEngine

app = FastAPI(title="模拟交易看板")
engine = SimEngine()

# 静态前端
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    p = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(p) if os.path.exists(p) else {"error": "前端缺失"}


@app.get("/api/dashboard")
def dashboard():
    return engine.get_dashboard()


@app.get("/api/kline")
def kline(symbol: str):
    bars = engine.klines.get(symbol, [])
    return {"symbol": symbol, "bars": bars}


@app.get("/api/daily_k")
def daily_k(symbol: str, source: str = "tencent"):
    """按需取日K，source: tencent(默认) / baostock / akshare。用于比对/核验数据源。"""
    if source not in ("tencent", "baostock", "akshare"):
        source = "tencent"
    bars = engine.daily_k_from(symbol, source)
    return {"symbol": symbol, "source": source, "bars": bars,
            "count": len(bars)}


@app.get("/api/params")
def get_params():
    return engine.params


@app.post("/api/params")
async def post_params(req: dict):
    engine.set_params(req)
    return {"ok": True, "params": engine.params}


@app.post("/api/scope")
async def post_scope(req: dict):
    engine.set_watchlist(req.get("astock", []), req.get("future", []))
    return {"ok": True}


@app.post("/api/universe/refresh")
async def post_universe_refresh():
    n = engine.refresh_universe()
    return {"ok": True, "universe_count": n}


@app.post("/api/reset")
async def post_reset():
    engine.manual_reset()
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = engine.get_dashboard()
            await ws.send_text(json.dumps(data, ensure_ascii=False))
            await asyncio.sleep(POLL_INTERVAL)
    except WebSocketDisconnect:
        pass


async def tick_loop():
    while True:
        try:
            await asyncio.to_thread(engine.tick)
        except Exception:
            pass
        await asyncio.sleep(POLL_INTERVAL)


@app.on_event("startup")
async def startup():
    # 启动即拉一次 K线，避免空窗
    try:
        await asyncio.to_thread(engine.refresh_klines)
    except Exception:
        pass
    asyncio.create_task(tick_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
