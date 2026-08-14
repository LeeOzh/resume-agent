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

JS_GO_TO_PAGE = '''(targetPage) => {
    const items = document.querySelectorAll('.eh-pagination__pagelist li');
    for (const el of items) {
        if (el.textContent.trim() === String(targetPage)) {
            el.click();
            return true;
        }
    }
    return false;
}'''

JS_GET_CURRENT_JOB = '''() => {
    const items = document.querySelectorAll('.job_name_text');
    for (const el of items) {
        const menuItem = el.closest('.menu-item_content');
        if (menuItem && menuItem.classList.contains('menu-item_content_active')) {
            return el.textContent.trim();
        }
    }
    return '';
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

JS_FIND_CANDIDATE_INDEX = '''(name) => {
    const items = document.querySelectorAll('.item.virtual_list');
    for (let i = 0; i < items.length; i++) {
        const nameEl = items[i].querySelector('.detail .firstline .name') || items[i].querySelector('.name');
        if (nameEl && nameEl.textContent.trim() === name) {
            return i;
        }
    }
    return -1;
}'''

JS_GET_ACTIVE_PAGE = '''() => {
    const active = document.querySelector('.eh-pagination__pagelist li.active, .eh-pagination li.active');
    if (active) {
        const n = parseInt(active.textContent.trim());
        if (!isNaN(n)) return n;
    }
    return 0;
}'''

JS_GET_FIRST_NAME = '''() => {
    const items = document.querySelectorAll('.item.virtual_list');
    if (items.length === 0) return '';
    const nameEl = items[0].querySelector('.detail .firstline .name');
    return nameEl ? nameEl.textContent.trim() : '';
}'''

JS_HAS_NEXT_PAGE = '''() => {
    const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
    if (!nextBtn) return false;
    return !(nextBtn.disabled || nextBtn.hasAttribute('disabled'));
}'''

JS_CLICK_NEXT = '''() => {
    const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
    if (!nextBtn) return false;
    nextBtn.click();
    return true;
}'''

JS_GET_TOTAL_PAGES = '''() => {
    let totalPages = 1;
    const items = document.querySelectorAll('.eh-pagination__pagelist li');
    for (const el of items) {
        const n = parseInt(el.textContent.trim());
        if (!isNaN(n) && n > totalPages) totalPages = n;
    }
    const totalEl = document.querySelector('.eh-pagination__total');
    if (totalEl) {
        const match = totalEl.textContent.match(/\\d+/);
        if (match) {
            const calc = Math.ceil(parseInt(match[0]) / 50);
            if (calc > totalPages) totalPages = calc;
        }
    }
    return totalPages;
}'''

JS_SCROLL_TO_TOP = '''() => {
    window.scrollTo(0, 0);
    const containers = document.querySelectorAll(
        '.list, [class*="virtual_list"], [class*="scroll"], .eh-virtual-scroll'
    );
    containers.forEach(el => { el.scrollTop = 0; });
}'''

JS_READ_RESUME_TEXT = '''() => {
    const selectors = [
        '.resume-content', '.resume-detail', '.resume-preview',
        '.attachment-content', '.file-content', '.pdf-content',
        '[class*="resume"]', '[class*="preview"]', '[class*="detail"]'
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 100) {
            return el.innerText.trim().substring(0, 8000);
        }
    }
    const body = document.body.innerText.trim();
    return body.substring(0, 8000);
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
        'pagination_scroll': '.eh-pagination, .eh-pagination__next, .pagination',
        'attachment_btn': '.attach_resume_item, #attachment, [class*="attachment"]',
        'download_btn': '.btn_item_download .download_a, .download_a, a.download_a, [class*="download"] a',
    }

    # 附件按钮候选（对齐 download_worker 原 selectors，含 has-text 兜底）
    ATTACHMENT_SELECTORS = [
        '.attach_resume_item',
        '#attachment',
        '[class*="attachment"]:has-text("附件个人信息")',
        '[class*="attachment"]',
    ]

    # 下载按钮候选（对齐 download_worker 原 selectors）
    DOWNLOAD_SELECTORS = [
        '.btn_item_download .download_a',
        '.download_a',
        'a.download_a',
        '[class*="download"] a',
    ]

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

    def go_to_page(self, driver, page_num: int) -> bool:
        if not page_num or page_num <= 1:
            return True
        clicked = driver.evaluate(JS_GO_TO_PAGE, page_num)
        return bool(clicked)

    def get_current_job(self, driver) -> str:
        result = driver.evaluate(JS_GET_CURRENT_JOB)
        return str(result or '')

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

    # ---------------- 下载能力 ----------------

    def has_next_page(self, driver) -> bool:
        try:
            return bool(driver.evaluate(JS_HAS_NEXT_PAGE))
        except Exception:
            return False

    def go_to_next_page(self, driver) -> bool:
        """点击下一页并等待翻页生效（页码变化优先，首名变化兜底）"""
        import time as _time
        try:
            current_page = driver.evaluate(JS_GET_ACTIVE_PAGE) or 0
            old_first = driver.evaluate(JS_GET_FIRST_NAME) or ''
            clicked = driver.evaluate(JS_CLICK_NEXT)
            if not clicked:
                return False
            for _ in range(20):
                _time.sleep(0.5)
                if current_page:
                    try:
                        now_page = driver.evaluate(JS_GET_ACTIVE_PAGE) or 0
                        if now_page and now_page != current_page:
                            return True
                    except Exception:
                        pass
                new_first = driver.evaluate(JS_GET_FIRST_NAME) or ''
                if new_first and new_first != old_first:
                    return True
            return False
        except Exception:
            return False

    def scroll_to_pagination(self, driver):
        """滚动到分页控件（scroll_into_view 优先，兜底滚轮）"""
        import time as _time
        el = driver.query_selector(self.selector('pagination_scroll'))
        if el is not None and driver.scroll_into_view(el, timeout=3000):
            _time.sleep(0.5)
            return
        for _ in range(5):
            try:
                driver.scroll_wheel(0, 800)
                _time.sleep(0.3)
            except Exception:
                break

    def find_candidate_by_name(self, driver, name: str):
        try:
            index = driver.evaluate(JS_FIND_CANDIDATE_INDEX, name)
            if index is None or index < 0:
                return None
            items = driver.query_selector_all(self.selector('candidate_item'))
            if 0 <= index < len(items):
                return items[index]
            return None
        except Exception:
            return None

    def find_name_element(self, driver, name: str):
        try:
            index = driver.evaluate(JS_FIND_CANDIDATE_INDEX, name)
            if index is None or index < 0:
                return None
            items = driver.query_selector_all(self.selector('candidate_item'))
            if 0 <= index < len(items):
                item = items[index]
                return (item.query_selector('.detail .firstline .name')
                        or item.query_selector('.name'))
            return None
        except Exception:
            return None

    def find_attachment_button(self, driver, timeout: int = 12):
        return driver.wait_for_element(self.ATTACHMENT_SELECTORS, timeout=timeout)

    def find_download_button(self, driver, timeout: int = 15):
        return driver.wait_for_element(self.DOWNLOAD_SELECTORS, timeout=timeout)

    def extract_resume_text(self, driver) -> str:
        try:
            return str(driver.evaluate(JS_READ_RESUME_TEXT) or '')
        except Exception:
            return ''

    def scroll_to_top(self, driver):
        try:
            driver.evaluate(JS_SCROLL_TO_TOP)
        except Exception:
            pass
