# -*- coding: utf-8 -*-
"""
TaskController - 任务控制器（Phase 3A）。

职责：接收 GUI 参数 -> 调用 TaskManager -> 返回结果。
- 不写状态机判断（状态流转留在 TaskManager）
- 不直接访问 Database（全部经 TaskManager）
- 异步 DB 线程生命周期在本类内持有引用，避免 QThread 被 GC 导致 Qt abort

结构：AutomationPage -> TaskController -> TaskManager -> Database
"""
from PyQt6.QtCore import QThread, pyqtSignal


class _TaskDbThread(QThread):
    """任务相关数据库后台操作线程（必须在完成前持有引用）"""
    finished = pyqtSignal()

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.func(*self.args, **self.kwargs)
        except Exception as e:
            print(f"任务DB操作失败: {e}")
        finally:
            self.finished.emit()


class TaskController:
    def __init__(self, db_path=None):
        from task import TaskManager
        self.tm = TaskManager(db_path)
        self._db_threads = []

    # ==================== 生命周期 ====================

    def create_and_start(self, job_name, ai_config, download_dir,
                         download_all, total, candidate_list_url,
                         selected_candidates=None):
        """
        GUI 层完整操作：创建任务 -> 写入候选人 -> 启动任务。
        全部经 TaskManager，不直接访问 DB。
        """
        task = self.tm.create_task(
            job_name=job_name,
            ai_config=ai_config if ai_config else {},
            download_dir=download_dir,
            download_all_pages=download_all,
            total_candidates=total,
            candidate_list_url=candidate_list_url,
        )
        if not task:
            return None
        self.tm.start_task(task.id)
        if selected_candidates:
            self.tm.add_candidates_batch(
                task.id,
                [dict(c, page=1, sort_index=i) for i, c in enumerate(selected_candidates)],
            )
        self.tm.log(task.id, 'task_log', f'开始下载 {total} 个候选人')
        return task.id

    def cancel_task(self, task_id, reason=''):
        self.tm.cancel_task(task_id, reason)

    def pause_task(self, task_id, reason=''):
        self.tm.pause_task(task_id, reason)

    def complete_task(self, task_id):
        self.tm.complete_task(task_id)

    def resume_task(self, task_id):
        self.tm.resume_task(task_id)

    def update_task_complete(self, task_id, total_pages, success_count,
                             fail_count, paused=False):
        """异步更新任务完成/暂停状态（线程引用由本类持有）"""

        def do_update():
            if not task_id:
                return
            self.tm.update_progress(task_id, total_pages=total_pages)
            if paused:
                self.tm.pause_task(task_id)
            else:
                self.tm.complete_task(task_id)
            self.tm.log(
                task_id, 'info',
                f'任务{"已暂停" if paused else "完成"}: 成功 {success_count}, 失败 {fail_count}',
            )

        self._run_async(do_update)

    def update_task_failed(self, task_id, error):
        """异步更新任务失败状态"""

        def do_update():
            if task_id:
                self.tm.fail_task(task_id, error)

        self._run_async(do_update)

    # ==================== 查询 ====================

    def get_task(self, task_id):
        return self.tm.get_task(task_id)

    def get_unfinished_tasks(self):
        return self.tm.get_unfinished_tasks()

    def get_task_stats(self, task_id):
        return self.tm.stats(task_id)

    def get_recoverable_candidates(self, task_id):
        return self.tm.get_recoverable_candidates(task_id)

    def restore_ai_config(self, task):
        """从任务快照恢复 AI 配置（task 为空返回 {}）"""
        if not task:
            return {}
        return self.tm.restore_ai_snapshot(getattr(task, 'ai_config_snapshot', ''))

    # ==================== 线程管理 ====================

    def _run_async(self, func, *args, **kwargs):
        thread = _TaskDbThread(func, *args, **kwargs)
        self._db_threads.append(thread)

        def _on_finished():
            if thread in self._db_threads:
                self._db_threads.remove(thread)

        thread.finished.connect(_on_finished)
        thread.start()
        return thread

    def shutdown(self, timeout_ms=3000):
        """退出前等待所有任务 DB 线程结束（防止 QThread 仍在运行导致 abort）"""
        for thread in list(self._db_threads):
            try:
                thread.wait(timeout_ms)
            except Exception:
                pass
        self._db_threads.clear()
