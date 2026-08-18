# -*- coding: utf-8 -*-
"""
BrowserManager - 浏览器生命周期统一管理（改造方案第 3 / 5 / 6 / 7 / 24 节）

统一收口：
- Chrome 启动 / 进程检测 / 调试端口检测
- Playwright 连接 / Context / Page 获取
- 浏览器健康检查
- 断线自动重连（最多3次，等待 3/5/10 秒）

现有业务代码不再到处 connect_over_cdp / subprocess.Popen，
统一通过本类访问。
"""
import socket
import subprocess
import threading
import time
from pathlib import Path

from .browser_config import (
    CHROME_DEBUG_PORT, CDP_ENDPOINT, get_profile_dir, find_chrome_path,
    RECONNECT_WAITS, URL_51JOB_TALENT_MANAGEMENT,
)
from .browser_state import BrowserState


# 进程级互斥锁：页面侧 BrowserController 与后台 BrowserMonitorThread 可能并发
# 触发 launch_chrome，需保证"检查端口 + 启动 Chrome"原子化，避免启动多个 Chrome。
_LAUNCH_LOCK = threading.Lock()


class BrowserManager:
    """Chrome 生命周期管理器"""

    def __init__(self, port: int = CHROME_DEBUG_PORT, profile_dir=None,
                 on_event=None):
        self.port = port
        self.cdp_endpoint = f"http://localhost:{port}"
        self.profile_dir = Path(profile_dir) if profile_dir else get_profile_dir()
        self.on_event = on_event  # 可选回调 on_event(event_type, message)

        self.state = BrowserState.DISCONNECTED
        self.last_error = ''

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.chrome_process = None

    # ==================== 事件/状态 ====================

    def _set_state(self, state):
        self.state = state

    def _emit(self, event_type: str, message: str):
        if self.on_event:
            try:
                self.on_event(event_type, message)
            except Exception:
                pass

    # ==================== 基础检测 ====================

    def is_debug_port_open(self) -> bool:
        """检测调试端口是否已打开"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', self.port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def is_chrome_running(self) -> bool:
        """检测是否存在 Chrome 进程（含用户日常 Chrome）"""
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                    return True
        except Exception:
            try:
                output = subprocess.check_output(
                    ['tasklist', '/FI', 'IMAGENAME eq chrome.exe'],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return b'chrome.exe' in output
            except Exception:
                pass
        return False

    # ==================== 启动 ====================

    def launch_chrome(self, wait_seconds: int = 30) -> bool:
        """启动独立 Profile 的 Chrome 调试模式，等待调试端口就绪"""
        self._set_state(BrowserState.STARTING)
        chrome_path = find_chrome_path()
        if not chrome_path:
            self.last_error = "未找到 Chrome，请先安装 Chrome"
            self._set_state(BrowserState.ERROR)
            return False

        try:
            # 互斥锁：防止多个 BrowserManager 实例（页面侧 + 监控线程）并发启动 Chrome
            with _LAUNCH_LOCK:
                if self.is_debug_port_open():
                    return True

                self.profile_dir.mkdir(parents=True, exist_ok=True)
                cmd = [
                    chrome_path,
                    f"--remote-debugging-port={self.port}",
                    f"--user-data-dir={self.profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                    "--disable-translate",
                    # 问题9：新版 Chrome 对 CDP 有 Origin 校验，缺少该参数会导致连接被拒
                    "--remote-allow-origins=*",
                ]
                self.chrome_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                for _ in range(wait_seconds):
                    time.sleep(1)
                    if self.is_debug_port_open():
                        self._emit('browser_started', f'Chrome 调试端口 {self.port} 已就绪')
                        return True

                self.last_error = f"等待 Chrome 调试端口超时（{wait_seconds}s）"
                self._set_state(BrowserState.ERROR)
                return False
        except Exception as e:
            self.last_error = f"启动Chrome失败: {e}"
            self._set_state(BrowserState.ERROR)
            return False

    # ==================== 连接 ====================

    def connect(self) -> bool:
        """连接已开放的调试端口（不自动启动）"""
        if not self.is_debug_port_open():
            self.last_error = f"调试端口 {self.port} 未开放"
            self._set_state(BrowserState.ERROR)
            return False

        self._set_state(BrowserState.CONNECTING)
        try:
            from playwright.sync_api import sync_playwright
            self._teardown_playwright()
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_endpoint)

            contexts = self.browser.contexts
            if not contexts:
                self.last_error = "未找到浏览器上下文"
                self._set_state(BrowserState.ERROR)
                return False
            self.context = contexts[0]

            pages = self.context.pages
            if pages:
                self.page = pages[-1]
            else:
                self.page = self.context.new_page()

            self._set_state(BrowserState.CONNECTED)
            return True
        except Exception as e:
            self.last_error = f"连接失败: {e}"
            self._set_state(BrowserState.ERROR)
            self._teardown_playwright()
            return False

    def initialize(self, auto_launch: bool = True) -> bool:
        """
        完整初始化：检测端口 -> 不存在则启动 -> 连接 -> 健康检查
        成功进入 READY，失败进入 ERROR 并返回 False
        """
        self._set_state(BrowserState.STARTING)
        if not self.is_debug_port_open():
            if auto_launch:
                self._emit('browser_starting', '正在启动 Chrome 调试模式...')
                if not self.launch_chrome():
                    return False
            else:
                self.last_error = f"调试端口 {self.port} 未开放"
                self._set_state(BrowserState.ERROR)
                return False

        if not self.connect():
            return False

        if self.health_check():
            self._set_state(BrowserState.READY)
            return True

        self._set_state(BrowserState.ERROR)
        return False

    # ==================== 健康检查 ====================

    def health_check(self) -> bool:
        """
        至少检查：
        1. Chrome 进程是否存在
        2. 调试端口是否可用
        3. Playwright 是否连接
        4. Browser 是否可用
        5. Page 是否可用
        """
        if not self.is_chrome_running() or not self.is_debug_port_open():
            return False
        if not self.playwright or not self.browser or not self.context:
            return False
        if not self.page:
            return False
        try:
            _ = self.page.url
            return True
        except Exception:
            return False

    def ensure_ready(self) -> bool:
        """健康检查不通过时自动重连（最多3次）"""
        if self.health_check():
            if self.state != BrowserState.READY:
                self._set_state(BrowserState.READY)
            return True
        return self.reconnect()

    # ==================== 重连 ====================

    def reconnect(self, max_attempts: int = 3) -> bool:
        """
        浏览器断开自动恢复（方案第 24 节）：
        暂停当前自动化动作 -> 尝试重新启动 Chrome -> 重新连接
        问题9：不再固定空等，先立即检查端口；仅在上一次尝试失败后短暂退避
        """
        self._set_state(BrowserState.RECONNECTING)
        self._emit('browser_disconnected', '检测到浏览器断开，正在自动重连...')
        self._teardown_playwright()

        for attempt in range(max_attempts):
            if attempt > 0:
                wait = RECONNECT_WAITS[min(attempt - 1, len(RECONNECT_WAITS) - 1)]
                time.sleep(wait)
                self._emit('browser_reconnecting', f'重连尝试 {attempt + 1}/{max_attempts}')

            if not self.is_debug_port_open():
                self._emit('browser_reconnecting', '调试端口未开放，正在重新启动 Chrome...')
                self.launch_chrome(wait_seconds=15)

            if self.connect() and self.health_check():
                self._set_state(BrowserState.READY)
                self._emit('browser_reconnected', '浏览器已重新连接')
                return True

        self.last_error = "浏览器自动重连失败，请手动检查 Chrome"
        self._set_state(BrowserState.ERROR)
        return False

    # ==================== 页面操作 ====================

    def get_page(self):
        """获取可用 Page（未连接时返回 None）"""
        if self.page:
            try:
                _ = self.page.url
                return self.page
            except Exception:
                pass
        return None

    def navigate_to(self, url: str, wait_seconds: int = 3) -> bool:
        """导航到指定页面"""
        page = self.get_page()
        if not page:
            return False
        try:
            page.goto(url)
            time.sleep(wait_seconds)
            return True
        except Exception:
            return False

    def goto_talent_management(self) -> bool:
        """打开前程无忧人才管理页"""
        return self.navigate_to(URL_51JOB_TALENT_MANAGEMENT)

    # ==================== 清理 ====================

    def _teardown_playwright(self):
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def close(self, close_chrome: bool = False):
        """关闭连接；close_chrome=True 时同时关闭自动启动的 Chrome 进程"""
        self._teardown_playwright()
        if close_chrome and self.chrome_process:
            try:
                self.chrome_process.terminate()
            except Exception:
                pass
            self.chrome_process = None
        self._set_state(BrowserState.DISCONNECTED)


# 兼容旧代码：确保调试模式已启动
def ensure_chrome_debug(port: int = CHROME_DEBUG_PORT, wait_seconds: int = 30) -> bool:
    manager = BrowserManager(port=port)
    return manager.initialize(auto_launch=True)
