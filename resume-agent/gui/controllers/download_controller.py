# -*- coding: utf-8 -*-
"""
DownloadController - 下载控制器（Phase 3D）。

职责（用户确认）：
- 把一个 download_worker 进程可靠地启动起来
- 提供 Process / Queue / stop_event / pause_event 的控制能力
- monitor reconnect 协调

不负责：TaskManager / CandidateService / AI 业务 / UI / 结果消费 / Excel 导出。
下载结果如何消费由页面决定（poll_result 返回原始 dict）。
"""
import multiprocessing
import time


class DownloadController:
    def __init__(self, monitor=None):
        self.monitor = monitor          # 引用，不拥有生命周期
        self.process = None
        self.queue = None
        self.stop_event = multiprocessing.Event()
        self.pause_event = multiprocessing.Event()
        self.start_time = None

    # ==================== 生命周期 ====================

    def start(self, candidates, download_dir, job_name, ai_config,
              download_all, task_id, db_path=None) -> bool:
        """启动下载子进程（进程/队列/Event 全部由本类管理）"""
        if self.is_worker_alive():
            return False
        self.clear_events()

        from gui.pages.automation_page import download_worker_target
        self.queue = multiprocessing.Queue()
        self.process = multiprocessing.Process(
            target=download_worker_target,
            args=(self.queue, candidates, download_dir, job_name,
                  ai_config, download_all, self.stop_event, task_id,
                  self.pause_event, db_path),
            daemon=True,
        )
        self.process.start()
        self.start_time = time.time()
        return True

    # ==================== 控制 ====================

    def pause(self):
        """请求暂停（当前候选人完成后暂停）"""
        self.pause_event.set()

    def stop(self):
        """请求中断下载"""
        self.stop_event.set()

    def clear_events(self):
        self.stop_event.clear()
        self.pause_event.clear()

    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    def is_pause_requested(self) -> bool:
        return self.pause_event.is_set()

    # ==================== 状态 / 轮询 ====================

    def is_worker_alive(self) -> bool:
        return bool(self.process and self.process.is_alive())

    def poll_result(self):
        """读取下载结果队列（进程未结束或队列空返回 None）"""
        if self.process is None:
            return None
        if self.process.is_alive():
            return None
        if self.queue is not None and not self.queue.empty():
            try:
                return self.queue.get()
            except Exception:
                return None
        return None

    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def kill_worker(self, timeout: int = 3):
        """强制终止下载子进程并清理"""
        if self.process and self.process.is_alive():
            try:
                self.process.terminate()
                self.process.join(timeout=timeout)
            except Exception:
                pass
        self.process = None
        self.queue = None
        self.start_time = None

    def shutdown_worker(self):
        """退出前清理（与 kill_worker 相同语义，供页面 shutdown 调用）"""
        self.kill_worker(timeout=5)

    # ==================== monitor 协调 ====================

    def set_monitor_reconnect(self, allowed: bool):
        if self.monitor is not None:
            self.monitor.set_reconnect_allowed(allowed)
