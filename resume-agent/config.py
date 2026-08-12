# -*- coding: utf-8 -*-
import sys
import os
import json
from pathlib import Path


def get_base_dir():
    """获取基础目录（兼容打包后的路径）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


# 项目根目录
BASE_DIR = get_base_dir()

# Chrome Remote Debugging 端口
CHROME_DEBUG_PORT = 9222

# Chrome Remote Debugging 地址
CDP_ENDPOINT = f"http://localhost:{CHROME_DEBUG_PORT}"

# Chrome 用户数据目录（改造方案第 4 节：独立 Profile，保存登录 Cookie）
try:
    from browser.browser_config import get_profile_dir
    CHROME_PROFILE_DIR = get_profile_dir()
except Exception:
    CHROME_PROFILE_DIR = Path(os.environ.get('LOCALAPPDATA', 'C:/')) / "ResumeAgent" / "chrome-profile"

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

# MiMo API 配置
MIMO_API_BASE = "https://api.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5-pro"

# AI 配置文件路径
AI_CONFIG_PATH = BASE_DIR / "ai_config.json"

# 前程无忧人才管理页面URL
URL_51JOB_TALENT_MANAGEMENT = "https://ehire.51job.com/Revision/talent/management"

# 前程无忧候选人页面URL（兼容旧代码）
URL_51JOB_CANDIDATES = "https://ehire.51job.com/candidates/resume/library.aspx"

# 学校名单文件路径
SCHOOL_LIST_PATH = BASE_DIR.parent / "2026可录用学校名单（软科排名300内）2026.4.30更新.xls"

# 学校过滤配置文件路径
SCHOOL_FILTER_CONFIG_PATH = BASE_DIR / "school_filter_config.json"


def load_ai_config():
    """加载 AI 配置"""
    if AI_CONFIG_PATH.exists():
        try:
            with open(AI_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 兼容旧格式：单个 match_description 迁移到 job_descriptions
                if "match_description" in config and "job_descriptions" not in config:
                    old_desc = config.pop("match_description")
                    config["job_descriptions"] = {"默认": old_desc} if old_desc else {}
                if "job_descriptions" not in config:
                    config["job_descriptions"] = {}
                return config
        except:
            pass
    return {"api_key": "", "job_descriptions": {}, "enabled": False}


def save_ai_config(config):
    """保存 AI 配置"""
    with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_school_filter_config():
    """加载学校过滤配置"""
    if SCHOOL_FILTER_CONFIG_PATH.exists():
        try:
            with open(SCHOOL_FILTER_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                if "school_list_path" in config:
                    return config
        except Exception:
            pass
    return {"school_list_path": str(SCHOOL_LIST_PATH)}


def save_school_filter_config(config):
    """保存学校过滤配置"""
    with open(SCHOOL_FILTER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
