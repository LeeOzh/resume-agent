# -*- coding: utf-8 -*-
"""
sites - 站点适配层（Phase 2）

SiteAdapter 提供"站点能力"（URL/选择器/页面检测/提取/解析），
不含流程编排（循环/等待/重试/去重属于 Workflow 职责）。
"""

from .base import SiteAdapter
from .site_51job import Site51Job
from .site_boss import SiteBoss

__all__ = ['SiteAdapter', 'Site51Job', 'SiteBoss']
