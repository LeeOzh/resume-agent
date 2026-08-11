@echo off
title HR简历自动下载助手

echo ========================================
echo   HR简历自动下载助手
echo ========================================
echo.

echo [提示] 程序将自动启动 Chrome 调试模式。
echo.
echo   请在打开的 Chrome 窗口中：
echo   1. 登录前程无忧
echo   2. 打开候选人列表页面
echo.
echo   程序会自动检测 Chrome 并刷新候选人列表。
echo.

pause

echo.
echo 正在启动程序...
echo.

set "EXE=%~dp0dist\AI简历批量初筛与下载助手.exe"
if not exist "%EXE%" set "EXE=%~dp0AI简历批量初筛与下载助手.exe"
if not exist "%EXE%" set "EXE=%~dp0resume-agent.exe"

if exist "%EXE%" (
    "%EXE%"
) else (
    echo 错误：未找到程序 exe
    echo 请确认已打包 dist\AI简历批量初筛与下载助手.exe
    pause
)