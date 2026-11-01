@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo  quant-simtrader  推送到 GitHub
echo ============================================
echo.
echo 前提：已在 GitHub 创建「公开(Public)」空仓库（不要勾 README/license）
echo.

set "REPO=%~1"
if "%REPO%"=="" (
  set /p REPO=请输入仓库名（直接回车默认 mack）:
)
if "%REPO%"=="" set "REPO=mack"

set "OWNER=srfdghnsr"
set "URL=https://github.com/%OWNER%/%REPO%.git"

echo.
echo 目标仓库: %URL%
echo.

git remote remove origin >nul 2>&1
git remote add origin "%URL%"

echo [1/2] 推送 main 分支（会弹出浏览器登录，授权一次即可）...
git push -u origin main
if errorlevel 1 goto FAIL

echo.
echo [2/2] 完成。
echo.
echo 接下来：
echo   - Actions 会自动开始跑（也可到仓库 Actions 页点 Run workflow 立即触发一次）
echo   - 首次运行后到 Settings - Pages 确认 Source = GitHub Actions
echo   - 看板地址: https://%OWNER%.github.io/%REPO%/
echo.
pause
exit /b 0

:FAIL
echo.
echo [失败] 推送未成功。常见原因：
echo   1) 仓库名或用户名不对
echo   2) 仓库不是「公开」的，或创建时勾选了 README（会与本地历史冲突）
echo   3) 浏览器登录未完成 / 无权限
echo.
pause
exit /b 1
