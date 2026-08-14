# -*- coding: utf-8 -*-
"""
SiteBoss - BOSS 直聘站点适配器（Phase 2D 骨架验证）。

目的：证明 ResumeCollectionWorkflow 是真正跨站点复用的，
而非"换皮的 51job Workflow"。

范围限制（用户确认）：
- 只实现 SiteAdapter 契约，不做真实 BOSS 自动化
- 不抓取真实 BOSS DOM；extract_* 返回 mock 数据供 Contract Test 验证
- 不修改 GUI / download_worker / DB / TaskManager

URL/selector 为 BOSS 已知占位，真实实现留待后续。
"""

from .base import SiteAdapter


class SiteBoss(SiteAdapter):
    """BOSS 直聘（zhipin.com）站点适配器（骨架）"""

    name = 'boss'
    domain = 'zhipin.com'

    # 逻辑名 -> URL（骨架占位，真实 URL 后续补充）
    URLS = {
        'talent_management': 'https://www.zhipin.com/web/talent',
    }

    # 逻辑名 -> CSS 选择器（骨架占位，真实 BOSS DOM 后续补充）
    SELECTORS = {
        'job_menu': '[data-job-menu]',
        'candidate_item': '[data-candidate-item]',
        'pagination_active': '[data-pagination-active]',
        'pagination_total': '[data-pagination-total]',
    }

    def url(self, name: str) -> str:
        if name in self.URLS:
            return self.URLS[name]
        raise KeyError(f'BOSS 未定义 URL 逻辑名: {name}')

    def selector(self, key: str) -> str:
        if key in self.SELECTORS:
            return self.SELECTORS[key]
        raise KeyError(f'BOSS 未定义选择器逻辑名: {key}')

    def detect_page(self, driver) -> str:
        """骨架：按 URL 判断页面类型（真实检测逻辑后续实现）"""
        try:
            url = driver.url
        except Exception:
            return 'UNKNOWN'
        if 'login' in url:
            return 'LOGIN_PAGE'
        if 'talent' in url:
            return 'CANDIDATE_LIST_PAGE'
        return 'UNKNOWN'

    def is_logged_in(self, driver) -> str:
        """骨架：登录状态由后续真实实现判断，当前默认 unknown"""
        return 'unknown'

    def login_expired_error(self) -> str:
        return 'BOSS 直聘登录状态已失效，请重新登录'

    # ---------------- 站点能力（骨架：mock 数据，验证 Workflow 契约） ----------------

    def extract_positions(self, driver) -> dict:
        return {
            'positions': [
                {'name': 'Java工程师', 'active': True},
                {'name': '前端工程师', 'active': False},
            ],
            'active': 'Java工程师',
        }

    def switch_job(self, driver, job_name: str) -> bool:
        return True

    def extract_pagination(self, driver) -> dict:
        return {'currentPage': 1, 'totalPages': 3}

    def extract_candidates(self, driver) -> list:
        return [
            {'name': '李四', 'school': '浙江大学', 'major': '软件工程', 'education': '硕士'},
            {'name': '王五', 'school': '华中科技大学', 'major': '计算机', 'education': '本科'},
        ]

    def parse_candidates(self, data: list) -> list:
        """与 Site51Job 相同的统一候选人结构（跨站点契约）"""
        candidates = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name', '') or '').strip()
            if not name or len(name) >= 20 or name == ' ':
                continue
            candidates.append({
                'name': name,
                'school': str(item.get('school', '') or '').strip(),
                'major': str(item.get('major', '') or '').strip(),
                'education': str(item.get('education', '') or '').strip(),
            })
        return candidates
