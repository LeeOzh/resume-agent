# -*- coding: utf-8 -*-
"""
Site51Job - 前程无忧站点适配器（Phase 2A）。

职责：51job 的 URL / 选择器 / 页面检测 / 提取 / 解析。
不含流程编排（Workflow 职责）。

说明：
- 提取 JS 从 browser_worker.py 迁移（语义逐字一致），Phase 2C 切换后删除 worker 内副本
- detect_page 暂包装现有 PageDetector（行为一致），后续将检测规则迁入本类
"""
import re

from .base import SiteAdapter
from browser.browser_config import URL_51JOB_TALENT_MANAGEMENT


# ---------------- 51job 提取 JS（语义与 browser_worker 一致） ----------------

JS_GET_POSITIONS = '''() => {
    const items = document.querySelectorAll('.job_name_text');
    const positions = [];
    let activeName = '';

    items.forEach(el => {
        const name = el.textContent.trim();
        if (!name) return;

        // 判断当前选中：检查menu-item_content是否有menu-item_content_active类
        const menuItemContent = el.closest('.menu-item_content');
        const isActive = menuItemContent ? menuItemContent.classList.contains('menu-item_content_active') : false;

        positions.push({ name: name, active: isActive });
        if (isActive) activeName = name;
    });

    return { positions: positions, active: activeName };
}'''

JS_SWITCH_JOB = '''(targetName) => {
    const items = document.querySelectorAll('.job_name_text');
    for (const el of items) {
        if (el.textContent.trim() === targetName) {
            const wrap = el.closest('.job_name_wrap') || el.closest('.menu-item') || el;
            wrap.click();
            return true;
        }
    }
    return false;
}'''

JS_GET_PAGINATION = '''() => {
    let currentPage = 1;
    let totalPages = 1;

    // 获取当前页码
    const active = document.querySelector('.eh-pagination__pagelist li.active');
    if (active) {
        const text = active.textContent.trim();
        const num = parseInt(text);
        if (!isNaN(num)) currentPage = num;
    }

    // 获取总页数（从分页控件的最后一页获取）
    const pageItems = document.querySelectorAll('.eh-pagination__pagelist li');
    if (pageItems.length > 0) {
        const lastPage = pageItems[pageItems.length - 1];
        const text = lastPage.textContent.trim();
        const num = parseInt(text);
        if (!isNaN(num)) totalPages = num;
    }

    // 也可以从总数和每页条数计算
    const totalEl = document.querySelector('.eh-pagination__total');
    if (totalEl) {
        const match = totalEl.textContent.match(/\\d+/);
        if (match) {
            const total = parseInt(match[0]);
            // 假设每页50条
            const calculatedPages = Math.ceil(total / 50);
            if (calculatedPages > totalPages) {
                totalPages = calculatedPages;
            }
        }
    }

    return { currentPage, totalPages };
}'''

JS_GET_CANDIDATES = '''() => {
    const items = document.querySelectorAll('.item.virtual_list');
    const candidates = [];

    items.forEach(item => {
        let name = '';
        let school = '';
        let major = '';
        let education = '';

        // 获取姓名
        const nameEl = item.querySelector('.detail .firstline .name')
            || item.querySelector('.name');
        if (nameEl) {
            name = nameEl.textContent.trim();
        }

        // 获取学校、专业、学历
        const schoolEl = item.querySelector('.school_name');
        if (schoolEl) {
            school = schoolEl.textContent.trim();
        }

        const majorEl = item.querySelector('.major_name');
        if (majorEl) {
            major = majorEl.textContent.trim();
        }

        // 获取学历
        const detailEl = item.querySelector('.name.context-detail');
        if (detailEl) {
            const spans = detailEl.querySelectorAll('span[title]');
            spans.forEach(span => {
                const title = span.getAttribute('title');
                if (title && (title === '本科' || title === '硕士' || title === '博士' || title === '大专' || title === '专科')) {
                    education = title;
                }
            });
        }

        if (name && name.length > 0 && name.length < 20 && name !== ' ') {
            candidates.push({
                name: name,
                school: school,
                major: major,
                education: education
            });
        }
    });

    return candidates;
}'''


class Site51Job(SiteAdapter):
    """前程无忧（ehire.51job.com）站点适配器"""

    name = '51job'
    domain = '51job.com'

    # 逻辑名 -> URL
    URLS = {
        'talent_management': URL_51JOB_TALENT_MANAGEMENT,
    }

    # 逻辑名 -> CSS 选择器
    SELECTORS = {
        'job_menu': '.job_name_text',
        'job_menu_active': '.menu-item_content.menu-item_content_active',
        'candidate_item': '.item.virtual_list',
        'candidate_name': '.detail .firstline .name',
        'candidate_name_fallback': '.name',
        'candidate_school': '.school_name',
        'candidate_major': '.major_name',
        'candidate_detail': '.name.context-detail',
        'pagination_list': '.eh-pagination__pagelist li',
        'pagination_active': '.eh-pagination__pagelist li.active',
        'pagination_total': '.eh-pagination__total',
    }

    def url(self, name: str) -> str:
        if name in self.URLS:
            return self.URLS[name]
        raise KeyError(f'51job 未定义 URL 逻辑名: {name}')

    def selector(self, key: str) -> str:
        if key in self.SELECTORS:
            return self.SELECTORS[key]
        raise KeyError(f'51job 未定义选择器逻辑名: {key}')

    def detect_page(self, driver) -> str:
        """检测页面类型（暂包装现有 PageDetector，后续迁入检测规则）"""
        from browser.page_detector import PageDetector
        return PageDetector.detect(page=getattr(driver, 'page', None))

    def is_logged_in(self, driver) -> str:
        """检测登录状态（暂包装 PageDetector.is_logged_in，后续迁入检测规则）"""
        from browser.page_detector import PageDetector
        return PageDetector.is_logged_in(page=getattr(driver, 'page', None))

    def login_expired_error(self) -> str:
        return '前程无忧登录状态已失效，请重新登录'

    def extract_positions(self, driver) -> dict:
        result = driver.evaluate(JS_GET_POSITIONS)
        return result or {'positions': [], 'active': ''}

    def switch_job(self, driver, job_name: str) -> bool:
        clicked = driver.evaluate(JS_SWITCH_JOB, job_name)
        return bool(clicked)

    def extract_pagination(self, driver) -> dict:
        result = driver.evaluate(JS_GET_PAGINATION)
        return result or {'currentPage': 1, 'totalPages': 1}

    def extract_candidates(self, driver) -> list:
        result = driver.evaluate(JS_GET_CANDIDATES)
        return result if isinstance(result, list) else []

    def parse_candidates(self, data: list) -> list:
        """
        原始数据 -> 统一候选人结构。
        保持与 browser_worker 现有输出一致：{name, school, major, education}
        （下游 automation_page / download_worker 依赖此结构）。
        """
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
