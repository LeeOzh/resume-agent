# -*- coding: utf-8 -*-
"""
browser/actions - 通用浏览器执行底座（Phase 1）

分层：
    ActionRunner -> Actions -> BrowserDriver -> Playwright Page

本阶段目标：为 Phase 2（SiteAdapter + Workflow）建立稳定的浏览器执行底座，
不绑定任何站点，不改变 browser_worker.py 对外接口与行为。
"""

from .context import ActionContext
from .resolver import TargetResolver
from .driver import BrowserDriver
from .actions import (
    Action, EvalAction, ExtractAction, ClickAction, ScrollAction,
    WaitAction, NavigateAction, FillAction, ScreenshotAction,
)
from .runner import ActionRunner

__all__ = [
    'ActionContext',
    'TargetResolver',
    'BrowserDriver',
    'Action',
    'EvalAction', 'ExtractAction', 'ClickAction', 'ScrollAction',
    'WaitAction', 'NavigateAction', 'FillAction', 'ScreenshotAction',
    'ActionRunner',
]
