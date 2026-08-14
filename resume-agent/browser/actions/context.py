# -*- coding: utf-8 -*-
"""
ActionContext - 动作执行上下文。

承载：浏览器驱动（BrowserDriver）、跨动作共享变量、日志回调。
动作之间通过 variables 传递数据（如提取结果、中间状态）。
"""


class ActionContext:
    def __init__(self, driver, variables=None, logger=None):
        self.driver = driver
        self.variables = variables if variables is not None else {}
        self.logger = logger or (lambda msg: None)

    def log(self, message: str):
        try:
            self.logger(message)
        except Exception:
            pass

    def get(self, key, default=None):
        return self.variables.get(key, default)

    def set(self, key, value):
        self.variables[key] = value
