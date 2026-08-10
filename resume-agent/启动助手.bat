@echo off
title HR简历自动下载助手

echo ========================================
echo   HR简历自动下载助手
echo ========================================
echo.

echo [提示] 请确保已按以下步骤操作：
echo.
echo   1. 已启动 Chrome 调试模式
echo   2. 已在 Chrome 中登录前程无忧
echo   3. 已打开候选人列表页面
echo.

pause

echo.
echo 正在启动程序...
echo.

if exist "%~dp0resume-agent.exe" (
    "%~dp0resume-agent.exe"
) else (
    echo 错误：未找到 resume-agent.exe
    echo 请确保所有文件在同一目录下
    pause
)