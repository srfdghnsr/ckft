# -*- coding: utf-8 -*-
"""云端运行入口包：供 GitHub Actions 等定时环境做「单轮执行 + 静态看板导出」。

本地实时服务仍在 backend/main.py（FastAPI + WebSocket），
两者共用同一套引擎与 data/state.json。
"""
