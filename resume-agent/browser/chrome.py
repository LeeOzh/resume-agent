# -*- coding: utf-8 -*-
"""
Chrome浏览器连接模块
支持自动检测、自动启动、自动连接
"""
import sys
import os
import time
import socket
import subprocess
import winreg
from pathlib import Path
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


class ChromeBrowser:
    """Chrome浏览器管理器，支持自动检测和启动"""

    def __init__(self, port=9222):
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.port = port
        self.cdp_endpoint = f"http://localhost:{port}"
        self.chrome_process = None
        self.profile_dir = Path(f"C:/chrome-debug-{port}")

    def find_chrome_path(self) -> str:
        """从注册表获取Chrome安装路径"""
        try:
            # 尝试从注册表获取
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
            )
            path = winreg.QueryValue(key, "")
            winreg.CloseKey(key)
            if os.path.exists(path):
                return path
        except Exception:
            pass

        # 尝试常见安装路径
        common_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path

        return None

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
        """检测Chrome是否正在运行"""
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                    return True
        except ImportError:
            # 如果没有psutil，使用tasklist
            try:
                output = subprocess.check_output(
                    ['tasklist', '/FI', 'IMAGENAME eq chrome.exe'],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return b'chrome.exe' in output
            except Exception:
                pass
        return False

    def launch_chrome(self) -> bool:
        """自动启动Chrome调试模式"""
        chrome_path = self.find_chrome_path()
        if not chrome_path:
            return False

        try:
            # 创建用户数据目录
            self.profile_dir.mkdir(parents=True, exist_ok=True)

            # 启动Chrome
            cmd = [
                chrome_path,
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "--disable-translate",
            ]

            self.chrome_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # 等待端口打开
            for _ in range(30):  # 最多等待30秒
                time.sleep(1)
                if self.is_debug_port_open():
                    return True

            return False

        except Exception as e:
            print(f"启动Chrome失败: {e}")
            return False

    def connect(self, auto_launch=True, wait_login=True) -> bool:
        """
        连接到Chrome浏览器

        Args:
            auto_launch: 是否自动启动Chrome
            wait_login: 是否等待用户登录

        Returns:
            是否连接成功
        """
        try:
            self.playwright = sync_playwright().start()

            # 1. 检测调试端口是否已打开
            if not self.is_debug_port_open():
                if auto_launch:
                    # 2. 自动启动Chrome
                    print("正在启动Chrome浏览器...")
                    if not self.launch_chrome():
                        print("启动Chrome失败，请手动启动Chrome并开启调试模式")
                        return False
                    print("Chrome已启动")
                else:
                    print(f"调试端口 {self.port} 未打开")
                    print(f"请使用以下命令启动Chrome:")
                    print(f'chrome.exe --remote-debugging-port={self.port} --user-data-dir=C:\\chrome-debug-{self.port}')
                    return False

            # 3. 连接到Chrome
            print("正在连接Chrome浏览器...")
            self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_endpoint)

            # 4. 获取上下文和页面
            contexts = self.browser.contexts
            if not contexts:
                print("错误：未找到浏览器上下文")
                return False

            self.context = contexts[0]
            pages = self.context.pages

            if not pages:
                # 创建新页面
                self.page = self.context.new_page()
            else:
                self.page = pages[-1]

            # 5. 检查是否需要等待登录
            if wait_login:
                self._check_and_wait_login()

            return True

        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def _check_and_wait_login(self):
        """检查并等待用户登录前程无忧"""
        try:
            current_url = self.page.url

            # 检查是否在前程无忧页面
            if '51job.com' not in current_url:
                # 导航到前程无忧人才管理页面
                print("正在打开前程无忧...")
                self.page.goto("https://ehire.51job.com/Revision/talent/management")
                time.sleep(3)

            # 检查是否需要登录
            if self._is_login_page():
                print("\n" + "=" * 50)
                print("  请在浏览器中登录前程无忧")
                print("  登录完成后，程序将自动继续")
                print("=" * 50 + "\n")

                # 等待登录完成
                self._wait_for_login()

                print("登录成功！")

            # 确保在人才管理页面
            self._ensure_talent_management_page()

        except Exception as e:
            print(f"检查登录状态失败: {e}")

    def _ensure_talent_management_page(self):
        """确保在人才管理页面"""
        try:
            current_url = self.page.url
            target_url = "https://ehire.51job.com/Revision/talent/management"

            # 如果不在人才管理页面，则跳转
            if 'talent/management' not in current_url and 'candidates' not in current_url:
                print("正在跳转到人才管理页面...")
                self.page.goto(target_url)
                time.sleep(3)
                print("已跳转到人才管理页面")

        except Exception as e:
            print(f"跳转人才管理页面失败: {e}")

    def _is_login_page(self) -> bool:
        """检测是否在登录页面"""
        try:
            # 检测登录页面特征
            login_indicators = [
                'login',
                'passport',
                '登录',
                '用户名',
                '密码',
            ]

            url = self.page.url.lower()
            for indicator in login_indicators:
                if indicator in url:
                    return True

            # 检测页面内容
            content = self.page.content().lower()
            login_count = sum(1 for ind in login_indicators if ind in content)
            return login_count >= 2

        except Exception:
            return False

    def _wait_for_login(self, timeout=300):
        """
        等待用户登录完成

        Args:
            timeout: 超时时间（秒），默认5分钟
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # 检测是否离开登录页面
                if not self._is_login_page():
                    # 等待页面稳定
                    time.sleep(2)
                    return True

                # 检测是否在候选人页面
                if 'candidates' in self.page.url or 'resume' in self.page.url:
                    return True

                time.sleep(1)

            except Exception:
                time.sleep(1)

        print("等待登录超时")
        return False

    def navigate_to_candidates(self) -> bool:
        """导航到候选人列表页面"""
        try:
            self.page.goto("https://ehire.51job.com/candidates/resume/library.aspx")
            time.sleep(3)
            return 'candidates' in self.page.url or 'resume' in self.page.url
        except Exception as e:
            print(f"导航失败: {e}")
            return False

    def get_current_page_info(self) -> dict:
        """获取当前页面信息"""
        if not self.page:
            return {"title": "", "url": ""}

        try:
            return {
                "title": self.page.title(),
                "url": self.page.url
            }
        except Exception as e:
            return {"title": "获取失败", "url": str(e)}

    def get_page_dom(self, selector: str = None) -> str:
        """获取页面 DOM 结构"""
        if not self.page:
            return ""

        try:
            if selector:
                element = self.page.query_selector(selector)
                if element:
                    return element.inner_html()
                return f"未找到匹配 '{selector}' 的元素"
            else:
                return self.page.content()
        except Exception as e:
            return f"获取 DOM 失败: {e}"

    def get_clickable_elements(self) -> list:
        """获取页面中可点击的元素"""
        if not self.page:
            return []

        try:
            elements = self.page.query_selector_all("a, button, [onclick], [role='button']")
            result = []
            for el in elements[:50]:
                tag = el.evaluate("el => el.tagName")
                text = el.inner_text()[:50] if el.inner_text() else ""
                href = el.get_attribute("href") or ""
                result.append({
                    "tag": tag,
                    "text": text.strip(),
                    "href": href
                })
            return result
        except Exception as e:
            return [{"error": str(e)}]

    def close(self):
        """关闭连接（不关闭浏览器）"""
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass