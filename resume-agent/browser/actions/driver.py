# -*- coding: utf-8 -*-
"""
BrowserDriver - 浏览器页面操作薄封装。

只负责"在浏览器里做什么"（goto/click/fill/wait/extract/scroll/screenshot 等），
不负责浏览器生命周期（启动/连接/重连 由 BrowserManager 负责）。

所有操作直接作用于 Playwright Page，异常向上抛出由调用方处理。
"""
import time


class BrowserDriver:
    def __init__(self, page, resolver=None):
        self.page = page
        self.resolver = resolver

    # ---------------- 基础信息 ----------------

    @property
    def url(self) -> str:
        return self.page.url

    def title(self) -> str:
        return self.page.title()

    # ---------------- 导航 ----------------

    def goto(self, url: str, wait_seconds: float = 0, timeout: int = 30000):
        self.page.goto(url, timeout=timeout)
        if wait_seconds:
            time.sleep(wait_seconds)

    def reload(self, wait_seconds: float = 0, timeout: int = 30000):
        self.page.reload(timeout=timeout)
        if wait_seconds:
            time.sleep(wait_seconds)

    # ---------------- 元素操作 ----------------

    def click(self, target: str, timeout: int = 10000):
        selector = self._resolve(target)
        self.page.click(selector, timeout=timeout)

    def fill(self, target: str, value: str, timeout: int = 10000):
        selector = self._resolve(target)
        self.page.fill(selector, value, timeout=timeout)

    def hover(self, target: str, timeout: int = 10000):
        selector = self._resolve(target)
        self.page.hover(selector, timeout=timeout)

    def query_selector(self, selector: str):
        """通用：按 CSS 选择器查找元素（返回 Playwright element 或 None）"""
        try:
            return self.page.query_selector(selector)
        except Exception:
            return None

    def query_selector_all(self, selector: str) -> list:
        try:
            return self.page.query_selector_all(selector)
        except Exception:
            return []

    def click_element(self, element):
        """通用：点击已定位的元素"""
        if element is None:
            return False
        try:
            element.click()
            return True
        except Exception:
            return False

    def scroll_into_view(self, element, timeout: int = 3000):
        try:
            element.scroll_into_view_if_needed(timeout=timeout)
            return True
        except Exception:
            return False

    def wait_for_element(self, selectors, timeout: int = 15):
        """通用：依次尝试 selectors 直到找到元素（对齐 download_worker 原逻辑）"""
        import time as _time
        deadline = _time.time() + timeout
        for sel in selectors:
            while _time.time() < deadline:
                el = self.query_selector(sel)
                if el is not None:
                    return el
                _time.sleep(0.3)
        return None

    # ---------------- 等待 ----------------

    def wait_for_selector(self, target: str, timeout: int = 10000, state='visible'):
        selector = self._resolve(target)
        self.page.wait_for_selector(selector, timeout=timeout, state=state)

    def wait_for_url(self, pattern, timeout: int = 10000):
        self.page.wait_for_url(pattern, timeout=timeout)

    def sleep(self, seconds: float):
        time.sleep(seconds)

    # ---------------- 弹窗 / 下载 / 上下文 ----------------

    def expect_popup(self, timeout: int = 5000):
        """通用：监听新标签页弹出（返回 context manager）"""
        return self.page.expect_popup(timeout=timeout)

    def expect_download(self, timeout: int = 20000):
        """通用：监听下载事件（返回 context manager）"""
        return self.page.expect_download(timeout=timeout)

    def context_pages(self) -> list:
        """通用：当前浏览器上下文的所有页面"""
        try:
            return list(self.page.context.pages)
        except Exception:
            return []

    def page_url(self) -> str:
        try:
            return self.page.url
        except Exception:
            return ''

    def page_title(self) -> str:
        try:
            return self.page.title()
        except Exception:
            return ''

    def close_page(self, page):
        try:
            page.close()
        except Exception:
            pass

    # ---------------- 提取 / 执行 ----------------

    def evaluate(self, expression, arg=None):
        """执行任意 JS 表达式，返回原始结果（业务逻辑的 JS 由调用方提供）"""
        return self.page.evaluate(expression, arg)

    def extract(self, expression, arg=None):
        """执行 JS 提取表达式，返回原始结果（与 evaluate 同构，语义上用于提取）"""
        return self.page.evaluate(expression, arg)

    def extract_list(self, expression, arg=None) -> list:
        """执行 JS 并强制返回 list"""
        result = self.page.evaluate(expression, arg)
        return result if isinstance(result, list) else []

    # ---------------- 鼠标 / 滚动 ----------------

    def mouse_move(self, x: int, y: int):
        self.page.mouse.move(x, y)

    def scroll_wheel(self, delta_x: int, delta_y: int):
        self.page.mouse.wheel(delta_x, delta_y)

    # ---------------- 截图 ----------------

    def screenshot(self, path: str = None, full_page: bool = False):
        if path:
            return self.page.screenshot(path=path, full_page=full_page)
        return self.page.screenshot(full_page=full_page)

    # ---------------- 内部 ----------------

    def _resolve(self, target: str) -> str:
        if self.resolver is not None:
            return self.resolver.resolve(target)
        return target
