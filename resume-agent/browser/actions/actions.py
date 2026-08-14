# -*- coding: utf-8 -*-
"""
原子 Action 集合（通用、与站点无关）。

每个 Action 通过 BrowserDriver 执行，可在 ActionRunner 中编排。
业务逻辑的 JS 脚本由调用方传入（Phase 2 将由 SiteAdapter 提供）。
"""


class Action:
    """Action 基类"""
    name = 'action'

    def execute(self, ctx) -> object:
        raise NotImplementedError

    def __call__(self, ctx):
        return self.execute(ctx)


class EvalAction(Action):
    """执行任意 JS 表达式"""
    name = 'eval'

    def __init__(self, expression, arg=None, into: str = None):
        self.expression = expression
        self.arg = arg
        self.into = into

    def execute(self, ctx) -> object:
        result = ctx.driver.evaluate(self.expression, self.arg)
        if self.into:
            ctx.set(self.into, result)
        return result


class ExtractAction(EvalAction):
    """语义化提取：执行 JS 提取表达式"""
    name = 'extract'


class ClickAction(Action):
    """点击目标（target 经 TargetResolver 解析）"""
    name = 'click'

    def __init__(self, target: str, timeout: int = 10000):
        self.target = target
        self.timeout = timeout

    def execute(self, ctx):
        return ctx.driver.click(self.target, timeout=self.timeout)


class FillAction(Action):
    """填写输入框"""
    name = 'fill'

    def __init__(self, target: str, value: str, timeout: int = 10000):
        self.target = target
        self.value = value
        self.timeout = timeout

    def execute(self, ctx):
        return ctx.driver.fill(self.target, self.value, timeout=self.timeout)


class ScrollAction(Action):
    """鼠标滚轮滚动"""
    name = 'scroll'

    def __init__(self, delta_x: int = 0, delta_y: int = 600):
        self.delta_x = delta_x
        self.delta_y = delta_y

    def execute(self, ctx):
        return ctx.driver.scroll_wheel(self.delta_x, self.delta_y)


class WaitAction(Action):
    """等待：元素可见 / URL 匹配 / 固定时长"""
    name = 'wait'

    def __init__(self, target: str = None, timeout: int = 10000,
                 state: str = 'visible', url_pattern=None, seconds: float = None):
        self.target = target
        self.timeout = timeout
        self.state = state
        self.url_pattern = url_pattern
        self.seconds = seconds

    def execute(self, ctx):
        if self.seconds is not None:
            return ctx.driver.sleep(self.seconds)
        if self.url_pattern:
            return ctx.driver.wait_for_url(self.url_pattern, timeout=self.timeout)
        if self.target:
            return ctx.driver.wait_for_selector(self.target, timeout=self.timeout, state=self.state)
        return None


class NavigateAction(Action):
    """导航到 URL"""
    name = 'navigate'

    def __init__(self, url: str, wait_seconds: float = 0, timeout: int = 30000):
        self.url = url
        self.wait_seconds = wait_seconds
        self.timeout = timeout

    def execute(self, ctx):
        return ctx.driver.goto(self.url, wait_seconds=self.wait_seconds, timeout=self.timeout)


class ScreenshotAction(Action):
    """截图"""
    name = 'screenshot'

    def __init__(self, path: str = None, full_page: bool = False):
        self.path = path
        self.full_page = full_page

    def execute(self, ctx):
        return ctx.driver.screenshot(path=self.path, full_page=self.full_page)
