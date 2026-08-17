# -*- coding: utf-8 -*-
"""
JobService - 职位数据同步（Phase 5A 残留清理）。

把刷新采集到的职位列表持久化到 jobs 表。属于 Job/Position 数据域，
与 CandidateService（候选人）、TaskController（任务）分离。
"""


class JobService:
    def __init__(self, db):
        self.db = db

    def sync_jobs(self, positions):
        """同步岗位列表到 jobs 表（upsert），返回 Job 列表"""
        return self.db.sync_jobs(positions)
