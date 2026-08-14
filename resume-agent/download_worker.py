# -*- coding: utf-8 -*-
"""
下载操作进程 - Worker 壳（Phase 4B-2）

职责仅剩：
1. 参数归一化 / TaskManager 初始化
2. BrowserManager 生命周期（启动/连接/关闭）
3. 组装 ResumeDownloadWorkflow 并执行
4. 异常兜底

业务流程全部在 workflow.resume_download，站点知识全部在 sites.site_51job。
"""
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))


def _error_dict(error: str, **extra) -> dict:
    """构造失败结果（与 Workflow result 同构）"""
    result = {
        'success': False,
        'results': [],
        'total_pages': 1,
        'current_page': 1,
        'error': error,
    }
    result.update(extra)
    return result


def run(candidates, download_dir, job_name='', ai_config=None,
        download_all_pages=False, stop_event=None, task_id=None, db_path=None,
        pause_event=None):
    """执行下载操作（生命周期壳 + Workflow 调用）"""
    from browser.browser_manager import BrowserManager
    from browser.actions import BrowserDriver
    from sites import Site51Job
    from task import TaskManager
    from bizflow import ResumeDownloadWorkflow

    # 兼容旧调用：candidates 为纯名字列表
    if candidates and isinstance(candidates[0], str):
        candidates = [{'name': n} for n in candidates]

    tm = None
    if task_id:
        try:
            tm = TaskManager(db_path) if db_path else TaskManager()
        except Exception:
            tm = None

    manager = BrowserManager()
    try:
        if not manager.initialize(auto_launch=True):
            return _error_dict(manager.last_error or '浏览器连接失败')

        context = manager.context
        page = manager.get_page()
        if not page or not context:
            return _error_dict('未找到打开的页面')

        driver = BrowserDriver(page)
        site = Site51Job()

        def refresh_driver():
            p = manager.get_page()
            return BrowserDriver(p) if p is not None else None

        workflow = ResumeDownloadWorkflow(
            driver=driver,
            site=site,
            task_manager=tm,
            stop_event=stop_event,
            pause_event=pause_event,
            ai_config=ai_config,
            browser_ready=lambda: (manager.health_check() or manager.reconnect()),
            refresh_driver=refresh_driver,
        )
        return workflow.run(
            candidates, download_dir, job_name,
            task_id=task_id, download_all_pages=download_all_pages,
        )
    except Exception as e:
        return _error_dict(str(e))
    finally:
        manager.close()
