# -*- coding: utf-8 -*-
"""
浏览器配置（改造方案第 4 节）

Chrome 使用独立 Profile：%LOCALAPPDATA%/ResumeAgent/chrome-profile
- 保存前程无忧登录 Cookie / LocalStorage
- 不接管用户日常 Chrome
"""
import os
from pathlib import Path

# Chrome Remote Debugging 端口
CHROME_DEBUG_PORT = 9222
CDP_ENDPOINT = f"http://localhost:{CHROME_DEBUG_PORT}"

# 独立 Profile 目录（方案要求，不使用 C:/chrome-agent）
def get_profile_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(base) / 'ResumeAgent' / 'chrome-profile'


PROFILE_DIR = get_profile_dir()

# 前程无忧地址（51job相关链接.txt）
URL_51JOB_LOGIN = "https://ehire.51job.com/Revision/login"
URL_51JOB_TALENT_MANAGEMENT = "https://ehire.51job.com/Revision/talent/management"

# 重连等待策略（秒）：第1次3秒 / 第2次5秒 / 第3次10秒
RECONNECT_WAITS = [3, 5, 10]


def find_chrome_path():
    """从注册表 / 常见路径查找 Chrome 可执行文件"""
    import subprocess
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        )
        path = winreg.QueryValue(key, "")
        winreg.CloseKey(key)
        if path and os.path.exists(path):
            return path
    except Exception:
        pass

    common_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return None
