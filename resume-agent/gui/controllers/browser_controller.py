# -*- coding: utf-8 -*-
"""
BrowserController - 浏览器控制器（Phase 3C）。

职责边界（用户确认）：
- 负责浏览器相关的执行与状态，不负责业务结果怎么消费
- 管理 refresh 子进程 / Queue（download 的 Process/Queue/Event 归 3D，不碰）
- 持有 browser_monitor 引用但不拥有其生命周期（main 创建/销毁）
- 站点操作经 SiteAdapter（switch_job/go_to_page 等，3C-3 接入）

结构：AutomationPage -> BrowserController -> BrowserManager / SiteAdapter / refresh worker
"""
import multiprocessing
import time


class BrowserController:
    def __init__(self, on_event=None, monitor=None):
        from browser.browser_manager import BrowserManager
        self.manager = BrowserManager(on_event=on_event)
        self.monitor = monitor          # 引用，不拥有生命周期
        self.site = None                # SiteAdapter（3C-3 注入）

        # refresh 子进程（download 的进程/队列 3D 再拆，不在此管理）
        self.refresh_process = None
        self.refresh_queue = None
        self.refresh_start_time = None

    # ==================== 生命周期 / 状态 ====================

    def ensure_ready(self) -> bool:
        """确保 Chrome 调试模式可用（health_check 通过或自动启动）"""
        if self.manager.health_check():
            return True
        try:
            return self.manager.initialize(auto_launch=True)
        except Exception:
            return False

    def get_page(self):
        return self.manager.get_page()

    def browser_state(self) -> str:
        return self.manager.state

    def set_monitor_reconnect(self, allowed: bool):
        """切换后台监控线程是否允许自动重连（任务运行期间关闭）"""
        if self.monitor is not None:
            self.monitor.set_reconnect_allowed(allowed)

    # ==================== 刷新采集（子进程编排） ====================

    def collect_candidates_async(self, switch_job='') -> bool:
        """
        启动刷新采集子进程（返回是否成功启动）。
        只负责启动与队列管理，结果消费由页面决定。
        """
        if self.is_worker_alive():
            return False
        if not self.ensure_ready():
            return False

        import browser_worker
        self.refresh_queue = multiprocessing.Queue()
        self.refresh_process = multiprocessing.Process(
            target=browser_worker.worker_main,
            args=(self.refresh_queue, switch_job),
            daemon=True,
        )
        self.refresh_process.start()
        self.refresh_start_time = time.time()
        return True

    def poll_result(self):
        """读取刷新结果队列（无结果返回 None）；进程未结束时返回 None"""
        if self.refresh_process is None:
            return None
        if self.refresh_process.is_alive():
            return None
        if self.refresh_queue is not None and not self.refresh_queue.empty():
            try:
                return self.refresh_queue.get()
            except Exception:
                return None
        return None

    def is_worker_alive(self) -> bool:
        return bool(self.refresh_process and self.refresh_process.is_alive())

    def refresh_elapsed(self) -> float:
        if self.refresh_start_time is None:
            return 0.0
        return time.time() - self.refresh_start_time

    def kill_worker(self, timeout: int = 3):
        """终止刷新子进程（看门狗超时用）"""
        if self.refresh_process and self.refresh_process.is_alive():
            try:
                self.refresh_process.terminate()
                self.refresh_process.join(timeout=timeout)
            except Exception:
                pass
        self.refresh_process = None
        self.refresh_queue = None
        self.refresh_start_time = None

    # ==================== 站点操作（3C-3 接入 SiteAdapter） ====================

    def _ensure_site(self):
        if self.site is None:
            from sites import Site51Job
            self.site = Site51Job()
        return self.site

    def switch_job(self, job_name: str) -> bool:
        """切换到指定岗位（站点能力，3C-3 接入）"""
        page = self.get_page()
        if not page:
            return False
        return self._ensure_site().switch_job(_driver_of(page), job_name)

    def go_to_page(self, page_num: int) -> bool:
        """定位到指定页码（站点能力，3C-3 接入）"""
        page = self.get_page()
        if not page or not page_num or page_num <= 1:
            return True
        return self._ensure_site().go_to_page(_driver_of(page), page_num)

    def get_login_status(self) -> str:
        page = self.get_page()
        if not page:
            return 'unknown'
        return self._ensure_site().is_logged_in(_driver_of(page))

    def get_page_type(self) -> str:
        page = self.get_page()
        if not page:
            return 'UNKNOWN'
        return self._ensure_site().detect_page(_driver_of(page))

    def get_current_job(self) -> str:
        page = self.get_page()
        if not page:
            return ''
        return self._ensure_site().get_current_job(_driver_of(page))


def _driver_of(page):
    """临时辅助：用页面构造 BrowserDriver（3C-3 统一注入方式后移除）"""
    from browser.actions import BrowserDriver, TargetResolver
    return BrowserDriver(page, resolver=TargetResolver())
