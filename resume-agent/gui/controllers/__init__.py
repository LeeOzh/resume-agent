# -*- coding: utf-8 -*-
"""GUI 控制器层：协调 UI 与领域层，不写业务判断"""

from .task_controller import TaskController
from .browser_controller import BrowserController
from .download_controller import DownloadController

__all__ = ['TaskController', 'BrowserController', 'DownloadController']
