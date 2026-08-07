import sys
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from config import CDP_ENDPOINT


class ChromeBrowser:
    """通过 Chrome Remote Debugging 连接已打开的 Chrome 浏览器"""

    def __init__(self):
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None

    def connect(self) -> bool:
        """连接到 Chrome CDP"""
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(CDP_ENDPOINT)

            # 获取已有的上下文和页面
            contexts = self.browser.contexts
            if not contexts:
                print("错误：未找到浏览器上下文，请确保 Chrome 已打开页面")
                return False

            self.context = contexts[0]
            pages = self.context.pages

            if not pages:
                print("错误：未找到打开的页面")
                return False

            # 使用当前活跃页面（最后一个）
            self.page = pages[-1]
            return True

        except Exception as e:
            print(f"连接失败: {e}")
            print(f"\n请确保 Chrome 已使用以下命令启动：")
            print(f'chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\chrome-agent')
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
        """获取页面 DOM 结构
        
        Args:
            selector: 可选，指定要获取的元素选择器
        """
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
        """获取页面中可点击的元素（用于调试）"""
        if not self.page:
            return []

        try:
            elements = self.page.query_selector_all("a, button, [onclick], [role='button']")
            result = []
            for el in elements[:50]:  # 限制数量
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
            self.playwright.stop()
