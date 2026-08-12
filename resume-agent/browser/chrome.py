# -*- coding: utf-8 -*-
"""
Chrome 浏览器连接模块（兼容层）

改造后统一由 BrowserManager 管理 Chrome 生命周期，
本模块保留 ChromeBrowser 旧接口供 CLI（main.py）等兼容使用。
"""
import time

from .browser_manager import BrowserManager
from .page_detector import PageDetector, PageType, LoginStatus


class ChromeBrowser:
    """Chrome浏览器管理器（兼容旧接口，内部委托 BrowserManager）"""

    def __init__(self, port=9222):
        self.manager = BrowserManager(port=port)
        self.port = port
        self.cdp_endpoint = f"http://localhost:{port}"
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.chrome_process = None
        self.profile_dir = self.manager.profile_dir

    def find_chrome_path(self) -> str:
        from .browser_config import find_chrome_path
        return find_chrome_path()

    def is_debug_port_open(self) -> bool:
        return self.manager.is_debug_port_open()

    def is_chrome_running(self) -> bool:
        return self.manager.is_chrome_running()

    def launch_chrome(self, wait_seconds=30) -> bool:
        ok = self.manager.launch_chrome(wait_seconds=wait_seconds)
        self.chrome_process = self.manager.chrome_process
        return ok

    def connect(self, auto_launch=True, wait_login=True) -> bool:
        """连接 Chrome；wait_login=True 时等待用户在前程无忧完成登录"""
        if not self.manager.initialize(auto_launch=auto_launch):
            return False

        self.playwright = self.manager.playwright
        self.browser = self.manager.browser
        self.context = self.manager.context
        self.page = self.manager.page

        if wait_login:
            self._check_and_wait_login()
        return True

    def _check_and_wait_login(self):
        """检查登录状态，未登录则引导用户登录并等待"""
        try:
            if not self.page:
                return
            status = PageDetector.is_logged_in(page=self.page)
            if status == LoginStatus.EXPIRED:
                print("\n" + "=" * 50)
                print("  请在浏览器中登录前程无忧")
                print("  登录完成后，程序将自动继续")
                print("=" * 50 + "\n")
                self._wait_for_login()
                print("登录成功！")
            self._ensure_talent_management_page()
        except Exception as e:
            print(f"检查登录状态失败: {e}")

    def _ensure_talent_management_page(self):
        """确保在人才管理页面"""
        try:
            page_type = PageDetector.detect(page=self.page)
            if page_type in (PageType.CANDIDATE_LIST_PAGE, PageType.RESUME_DETAIL):
                return
            if page_type not in (PageType.LOGIN_PAGE, PageType.UNKNOWN, PageType.OTHER_PAGE):
                return
            print("正在跳转到人才管理页面...")
            self.manager.goto_talent_management()
            print("已跳转到人才管理页面")
        except Exception as e:
            print(f"跳转人才管理页面失败: {e}")

    def _is_login_page(self) -> bool:
        try:
            return PageDetector.detect(page=self.page) == PageType.LOGIN_PAGE
        except Exception:
            return False

    def _wait_for_login(self, timeout=300):
        """等待用户登录完成"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                if not self._is_login_page():
                    time.sleep(2)
                    return True
                time.sleep(1)
            except Exception:
                time.sleep(1)
        print("等待登录超时")
        return False

    def navigate_to_candidates(self) -> bool:
        return self.manager.navigate_to("https://ehire.51job.com/candidates/resume/library.aspx")

    def get_current_page_info(self) -> dict:
        if not self.page:
            return {"title": "", "url": ""}
        try:
            return {
                "title": self.page.title(),
                "url": self.page.url,
                "page_type": PageDetector.detect(page=self.page),
                "login_status": PageDetector.is_logged_in(page=self.page),
            }
        except Exception as e:
            return {"title": "获取失败", "url": str(e)}

    def get_page_dom(self, selector: str = None) -> str:
        if not self.page:
            return ""
        try:
            if selector:
                element = self.page.query_selector(selector)
                if element:
                    return element.inner_html()
                return f"未找到匹配 '{selector}' 的元素"
            return self.page.content()
        except Exception as e:
            return f"获取 DOM 失败: {e}"

    def get_clickable_elements(self) -> list:
        if not self.page:
            return []
        try:
            elements = self.page.query_selector_all("a, button, [onclick], [role='button']")
            result = []
            for el in elements[:50]:
                tag = el.evaluate("el => el.tagName")
                text = el.inner_text()[:50] if el.inner_text() else ""
                href = el.get_attribute("href") or ""
                result.append({"tag": tag, "text": text.strip(), "href": href})
            return result
        except Exception as e:
            return [{"error": str(e)}]

    def close(self):
        self.manager.close()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None


def ensure_chrome_debug(port=9222, wait_seconds=30) -> bool:
    """确保 Chrome 调试模式已启动（兼容旧代码）"""
    manager = BrowserManager(port=port)
    return manager.initialize(auto_launch=True)
