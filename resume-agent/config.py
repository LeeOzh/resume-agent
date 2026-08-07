# -*- coding: utf-8 -*-
import sys
import os
from pathlib import Path


def get_base_dir():
    """获取基础目录（兼容打包后的路径）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


# 项目根目录
BASE_DIR = get_base_dir()

# Chrome Remote Debugging 地址
CDP_ENDPOINT = "http://localhost:9222"

# 下载路径
DOWNLOAD_PATH = BASE_DIR / "output" / "resumes"

# 最大下载数量
MAX_DOWNLOAD = 100

# 页面等待时间（秒）
WAIT_TIME = 3

# 日志路径
LOG_PATH = BASE_DIR / "logs" / "app.log"

# 结果输出路径
RESULT_PATH = BASE_DIR / "output" / "result.xlsx"
