# -*- coding: utf-8 -*-
"""
workflow - 采集业务流程层（Phase 2C）

ResumeCollectionWorkflow 只负责"怎么采集"（登录分支/滚动循环/去重/终止），
不接触浏览器生命周期、站点实现、跨进程通信、GUI、DB。
"""

from .resume_collection import CollectionResult, ResumeCollectionWorkflow
from .resume_download import ResumeDownloadWorkflow, evaluate_resume

__all__ = ['CollectionResult', 'ResumeCollectionWorkflow',
           'ResumeDownloadWorkflow', 'evaluate_resume']
