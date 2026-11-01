@echo off
chcp 65001 >nul
:: 模拟交易看板启动脚本
:: 使用 WorkBuddy 自带的托管 Python（含 fastapi/uvicorn）
setlocal
set PY="C:/Users/尹先生/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
:: 本地服务绕过代理（否则请求被代理吃掉）
set NO_PROXY=127.0.0.1,localhost,::1
set no_proxy=127.0.0.1,localhost,::1
cd /d "%~dp0"
echo 正在启动模拟交易看板…
echo 浏览器打开: http://127.0.0.1:9528/
%PY% -m backend.main
pause
