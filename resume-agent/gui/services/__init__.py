# -*- coding: utf-8 -*-
"""GUI 服务层：候选人的业务数据管理（不碰浏览器/任务状态/AI/下载）"""

from .candidate_service import CandidateService
from .job_service import JobService

__all__ = ['CandidateService', 'JobService']
