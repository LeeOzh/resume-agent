# -*- coding: utf-8 -*-
"""
TaskManager - 任务生命周期管理（改造方案第 11 / 19 / 20 / 21 / 25 节）

职责：
- 创建/查询/暂停/恢复/完成/取消任务
- 候选人状态机持久化（pending -> processing -> ai_rejected/downloading -> downloaded/failed）
- 每个候选人处理完立即写入数据库（禁止攒到最后一次性保存）
- AI 配置快照：任务创建时保存，运行期间不受全局配置修改影响
"""
import json
from typing import List, Optional

from db import Database, Task, TaskCandidate
from .task_state import (
    TASK_PENDING, TASK_RUNNING, TASK_PAUSED, TASK_COMPLETED,
    TASK_FAILED, TASK_CANCELLED, TASK_ACTIVE,
    CAND_PENDING, CAND_PROCESSING, CAND_AI_REJECTED,
    CAND_DOWNLOADING, CAND_DOWNLOADED, CAND_FAILED, CAND_TERMINAL, CAND_RECOVERABLE,
    EVENT_TASK_STARTED, EVENT_TASK_PAUSED, EVENT_TASK_RESUMED, EVENT_TASK_COMPLETED,
    EVENT_CANDIDATE_PROCESSING, EVENT_AI_MATCHED, EVENT_AI_REJECTED,
    EVENT_DOWNLOAD_STARTED, EVENT_DOWNLOAD_SUCCESS, EVENT_DOWNLOAD_FAILED,
)


def build_ai_snapshot(ai_config: Optional[dict]) -> str:
    """把 AI 配置序列化为快照 JSON（任务创建时调用）"""
    return json.dumps(ai_config or {}, ensure_ascii=False)


def restore_ai_snapshot(snapshot: str) -> dict:
    """从快照 JSON 恢复 AI 配置"""
    if not snapshot:
        return {}
    try:
        cfg = json.loads(snapshot)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


class TaskManager:
    """任务生命周期管理器，内部封装 Database"""

    def __init__(self, db_path: str = None):
        self.db = Database(db_path)

    # ==================== 任务生命周期 ====================

    def create_task(self, job_name: str, ai_config: Optional[dict],
                    download_dir: str, download_all_pages: bool = False,
                    total_candidates: int = 0, candidate_list_url: str = '',
                    job_id: int = None, external_job_id: str = '') -> Optional[Task]:
        """创建任务（只有用户点击开始下载时才创建），并保存 AI 配置快照"""
        task = self.db.create_task(
            job_name=job_name,
            ai_config=ai_config or {},
            download_dir=download_dir,
            download_all_pages=download_all_pages,
            total_candidates=total_candidates,
            candidate_list_url=candidate_list_url,
            job_id=job_id,
            external_job_id=external_job_id,
        )
        if task:
            self.log(task.id, EVENT_TASK_STARTED, f'任务创建: {job_name}')
        return task

    @staticmethod
    def restore_ai_snapshot(snapshot: str) -> dict:
        """从任务快照恢复 AI 配置（方案第 19 节）"""
        return restore_ai_snapshot(snapshot)

    def get_task(self, task_id: int) -> Optional[Task]:
        return self.db.get_task(task_id)

    def get_unfinished_tasks(self) -> List[Task]:
        """查询 status IN (running, paused) 的未完成任务"""
        return self.db.get_unfinished_tasks()

    def start_task(self, task_id: int):
        self.db.update_task_status(task_id, TASK_RUNNING)

    def pause_task(self, task_id: int, reason: str = ''):
        """暂停任务：当前候选人完成后再暂停（worker 在下一次循环检查）"""
        self.db.update_task_status(task_id, TASK_PAUSED)
        self.log(task_id, EVENT_TASK_PAUSED, f'任务已暂停: {reason}' if reason else '任务已暂停')

    def resume_task(self, task_id: int):
        self.db.update_task_status(task_id, TASK_RUNNING)
        self.log(task_id, EVENT_TASK_RESUMED, '任务恢复运行')

    def complete_task(self, task_id: int):
        self.db.update_task_status(task_id, TASK_COMPLETED)
        self.log(task_id, EVENT_TASK_COMPLETED, '任务完成')

    def fail_task(self, task_id: int, error: str = ''):
        self.db.update_task_status(task_id, TASK_FAILED)
        self.log(task_id, EVENT_TASK_COMPLETED, f'任务失败: {error}', level='error')

    def cancel_task(self, task_id: int, reason: str = ''):
        self.db.update_task_status(task_id, TASK_CANCELLED)
        self.log(task_id, EVENT_TASK_PAUSED, f'任务已取消: {reason}')

    def update_progress(self, task_id: int, **stats):
        self.db.update_task_progress(task_id, **stats)

    # ==================== 候选人状态 ====================

    def upsert_candidate(self, task_id: int, candidate: dict) -> TaskCandidate:
        """UPSERT 候选人到 task_candidates（立即保存，不批量）"""
        return self.db.add_candidate(task_id, candidate)

    def mark_candidate_processing(self, task_id: int, external_id: str):
        self.db.update_candidate_status(task_id, external_id, CAND_PROCESSING)
        self.log(task_id, EVENT_CANDIDATE_PROCESSING, f'开始处理候选人 {external_id[:12]}...',
                 candidate_id=None)

    def save_ai_result(self, task_id: int, external_id: str,
                       ai_pass: bool, ai_reason: str, ai_score: float = 0.0):
        """保存 AI 评估结果；不通过时状态自动切为 ai_rejected"""
        self.db.update_candidate_ai_result(task_id, external_id, ai_pass, ai_reason, ai_score)
        event = EVENT_AI_MATCHED if ai_pass else EVENT_AI_REJECTED
        self.log(task_id, event, f'AI评估: {"通过" if ai_pass else "不通过"} - {ai_reason}')

    def mark_candidate_downloading(self, task_id: int, external_id: str):
        self.db.update_candidate_status(task_id, external_id, CAND_DOWNLOADING)
        self.log(task_id, EVENT_DOWNLOAD_STARTED, f'开始下载 {external_id[:12]}...')

    def mark_candidate_downloaded(self, task_id: int, external_id: str, file_path: str = ''):
        self.db.update_candidate_status(task_id, external_id, CAND_DOWNLOADED, file_path=file_path)
        self.log(task_id, EVENT_DOWNLOAD_SUCCESS, f'下载完成: {file_path or external_id[:12]}')

    def mark_candidate_failed(self, task_id: int, external_id: str, error: str = ''):
        self.db.update_candidate_status(task_id, external_id, CAND_FAILED, error_message=error)
        self.log(task_id, EVENT_DOWNLOAD_FAILED, f'处理失败: {error}', level='error')

    def get_recoverable_candidates(self, task_id: int) -> List[TaskCandidate]:
        """恢复任务时获取可处理候选人（跳过 downloaded/ai_rejected）"""
        return self.db.get_recoverable_candidates(task_id)

    def get_candidates(self, task_id: int) -> List[TaskCandidate]:
        return self.db.get_task_candidates(task_id)

    def stats(self, task_id: int) -> dict:
        return self.db.get_task_stats(task_id)

    def save_candidate_result(self, task_id: int, candidate: dict, page_num: int,
                              download_result: dict, progress: dict = None):
        """单事务保存候选人处理结果与任务进度（问题11：减少连接次数）"""
        return self.db.save_candidate_result(
            task_id, candidate, page_num, download_result, progress
        )

    # ==================== 日志 ====================

    def log(self, task_id: int, event_type: str, message: str,
            level: str = 'info', candidate_id: int = None):
        try:
            self.db.add_task_log(task_id, level, message, event_type=event_type,
                                 candidate_id=candidate_id)
        except Exception:
            pass
