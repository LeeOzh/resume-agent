# -*- coding: utf-8 -*-
"""
浏览器操作进程 - 在独立进程中运行（Phase 2C 薄壳）

职责仅剩：
1. BrowserManager 生命周期（启动/连接/关闭）
2. 组装 SiteAdapter + BrowserDriver + ResumeCollectionWorkflow
3. 执行 Workflow，把 CollectionResult 序列化为 dict 返回

业务流程全部在 workflow.resume_collection 中，51job 知识全部在 sites.site_51job。
对外接口 run(switch_job) -> dict 保持不变。
"""
import sys
import json
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))


def _error_dict(error: str) -> dict:
    """构造失败结果（与 CollectionResult.to_dict() 同构，兼容旧 GUI）"""
    return {
        'success': False,
        'candidates': [],
        'positions': [],
        'active_position': '',
        'page_title': '',
        'page_url': '',
        'page_type': '',
        'login_status': '',
        'current_page': 1,
        'total_pages': 1,
        'error': error,
    }


def run(switch_job=''):
    """执行浏览器连接和候选人获取（生命周期壳 + Workflow 调用 + dict 序列化）"""
    from browser.browser_manager import BrowserManager
    from browser.actions import BrowserDriver, TargetResolver
    from sites import Site51Job
    from workflow import ResumeCollectionWorkflow

    manager = BrowserManager()
    try:
        if not manager.initialize(auto_launch=True):
            return _error_dict(manager.last_error or '浏览器连接失败')

        page = manager.get_page()
        if not page:
            return _error_dict('未找到可用页面')

        site = Site51Job()
        driver = BrowserDriver(page, resolver=TargetResolver(site))
        workflow = ResumeCollectionWorkflow(driver=driver, site=site)
        result = workflow.run(switch_job)
        return result.to_dict()
    except Exception as e:
        return _error_dict(str(e))
    finally:
        manager.close()


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--switch', type=str, default='', help='切换到指定职位')
    args = parser.parse_args()

    result = run(args.switch)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
