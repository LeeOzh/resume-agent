@echo off
title 启动Chrome调试模式

echo ========================================
echo   启动 Chrome 调试模式
echo ========================================
echo.

echo 正在启动 Chrome...
echo.

start "" "chrome.exe" --remote-debugging-port=9222 --user-data-dir=%LOCALAPPDATA%\ResumeAgent\chrome-profile --remote-allow-origins=*

echo Chrome 已启动！
echo.
echo 请在 Chrome 中：
echo   1. 登录前程无忧
echo   2. 打开候选人列表页面
echo.
echo 然后运行 "启动助手.bat" 开始下载简历
echo.
pause