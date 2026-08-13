# -*- coding: utf-8 -*-
"""
微信监听配置：保存目录 / 群名 / 轮询间隔 / 公司前缀列表
配置文件：wechat_config.json（与 exe 同级；未打包时为项目根目录）
"""
import json
import sys
from pathlib import Path


def _get_base_dir() -> Path:
    """获取基础目录（兼容打包后路径）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


WECHAT_CONFIG_PATH = _get_base_dir() / "wechat_config.json"

DEFAULT_CONFIG = {
    # 文件保存目录（相对路径按项目根目录解析）
    "save_dir": "output/wechat_resumes",
    # 微信聊天文件目录（自动检测失败时可手动指定；留空则自动检测）
    "chatfile_dir": "",
    # 文件名中的公司前缀（解析姓名时先去掉）
    "company_prefixes": ["广州海颐", "海颐"],
    # 消息轮询间隔（秒）
    "poll_interval": 2.0,
    # 上次监听的群名（打开页面时自动选中）
    "last_group": "",
}


def load_wechat_config() -> dict:
    """加载微信监听配置，缺失字段用默认值补齐"""
    config = dict(DEFAULT_CONFIG)
    if WECHAT_CONFIG_PATH.exists():
        try:
            with open(WECHAT_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in DEFAULT_CONFIG:
                    if key in data and data[key] not in (None, ""):
                        config[key] = data[key]
        except Exception:
            pass
    return config


def save_wechat_config(config: dict) -> None:
    """保存微信监听配置"""
    merged = dict(DEFAULT_CONFIG)
    merged.update(config or {})
    try:
        with open(WECHAT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def resolve_save_dir(config: dict = None) -> Path:
    """解析保存目录（相对路径 -> 项目根目录下的绝对路径），不存在则创建"""
    config = config or load_wechat_config()
    raw = str(config.get("save_dir") or DEFAULT_CONFIG["save_dir"])
    path = Path(raw)
    if not path.is_absolute():
        path = _get_base_dir() / path
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path
