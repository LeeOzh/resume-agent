# -*- coding: utf-8 -*-
"""
PageDetector - 前程无忧页面状态检测（改造方案第 8 / 9 / 10 节）

detect()      返回当前页面类型（UNKNOWN/LOGIN_PAGE/HOME_PAGE/JOB_LIST_PAGE/
              CANDIDATE_LIST_PAGE/RESUME_DETAIL/OTHER_PAGE）
is_logged_in()返回登录状态（logged_in/expired/unknown）
get_current_job() 返回当前选中岗位

判断依据组合：URL + 页面标题 + DOM 特征 + 页面特征元素（参考目录 txt 分析）：
- 登录页：eh_login / login_main / login_area / qr_code_wrap / login_btn / 扫码登录
- 候选人列表：.item.virtual_list
- 职位菜单：.job_name_text
- 简历详情：附件个人信息 / 工作经历 / 教育经历
"""
import re


class PageType:
    UNKNOWN = 'UNKNOWN'
    LOGIN_PAGE = 'LOGIN_PAGE'
    HOME_PAGE = 'HOME_PAGE'
    JOB_LIST_PAGE = 'JOB_LIST_PAGE'
    CANDIDATE_LIST_PAGE = 'CANDIDATE_LIST_PAGE'
    RESUME_DETAIL = 'RESUME_DETAIL'
    OTHER_PAGE = 'OTHER_PAGE'


class LoginStatus:
    LOGGED_IN = 'logged_in'
    EXPIRED = 'expired'
    UNKNOWN = 'unknown'


# 51job ehire 域名特征
EHIRE_DOMAIN = '51job.com'

# 登录页 URL 特征
LOGIN_URL_MARKERS = ('/login', 'passport', 'login.aspx')

# 候选人列表 URL 特征
CANDIDATE_URL_MARKERS = ('talent/management', 'resume/library', 'candidates')


class PageDetector:
    """页面检测器（纯函数式，可对 Page 或静态特征调用）"""

    @staticmethod
    def _features_from_html(html: str) -> dict:
        """从 HTML 文本提取特征（用于离线调试/单元测试）"""
        html = html or ''
        return {
            'has_virtual_list': '.item.virtual_list' in html or 'virtual_list' in html,
            'has_job_menu': '.job_name_text' in html or 'job_name_text' in html,
            'has_login_page': any(k in html for k in (
                'eh_login', 'login_main', 'login_area', 'login_body',
                'qr_code_wrap', 'login_btn',
            )),
            'has_resume_detail': (
                '附件个人信息' in html and
                ('工作经历' in html or '教育经历' in html)
            ),
            'has_password_input': 'type="password"' in html or "type='password'" in html,
        }

    @staticmethod
    def _collect_features(page) -> dict:
        """从 Playwright Page 提取页面特征"""
        try:
            return page.evaluate('''() => {
                const bodyText = document.body ? document.body.innerText : '';
                const q = (s) => !!document.querySelector(s);
                return {
                    has_virtual_list: q('.item.virtual_list') || q('[class*="virtual_list"]'),
                    has_job_menu: q('.job_name_text'),
                    has_login_page: q('.eh_login') || q('.login_main') ||
                        q('.login_area') || q('.login_body') || q('.qr_code_wrap') ||
                        q('.login_btn') || q('#login') ||
                        !!document.querySelector('input[type="password"]'),
                    has_resume_detail: q('.attachment-content') || q('.attachment_info') ||
                        (bodyText.includes('附件个人信息') &&
                         (bodyText.includes('工作经历') || bodyText.includes('教育经历'))),
                    has_user_area: q('.userInfo, .user-info, .header-user, .user_center, .navbar-user'),
                    has_logout_text: bodyText.includes('退出') || bodyText.includes('安全退出'),
                    body_text: bodyText.substring(0, 3000),
                };
            }''')
        except Exception:
            return {}

    @classmethod
    def detect(cls, page=None, url: str = '', title: str = '', html: str = '') -> str:
        """
        检测当前页面类型

        Args:
            page: Playwright Page（优先）
            url/title/html: 离线检测时的静态信息
        """
        if page is not None:
            try:
                url = page.url or url
                title = page.title() or title
            except Exception:
                pass

        features = {}
        if page is not None:
            features = cls._collect_features(page)
        elif html:
            features = cls._features_from_html(html)

        url_lower = (url or '').lower()

        # 1. 登录页：URL 或 DOM 特征
        if any(m in url_lower for m in LOGIN_URL_MARKERS):
            return PageType.LOGIN_PAGE
        if features.get('has_login_page') or features.get('has_password_input'):
            return PageType.LOGIN_PAGE

        # 2. 非 51job 页面
        if EHIRE_DOMAIN not in url_lower and not any(features.values()):
            return PageType.OTHER_PAGE

        # 3. 候选人列表：DOM 特征优先，URL 兜底
        if features.get('has_virtual_list'):
            return PageType.CANDIDATE_LIST_PAGE
        if any(m in url_lower for m in CANDIDATE_URL_MARKERS):
            return PageType.CANDIDATE_LIST_PAGE

        # 4. 简历详情
        if features.get('has_resume_detail'):
            return PageType.RESUME_DETAIL

        # 5. 职位列表（人才管理首页含职位菜单）
        if features.get('has_job_menu'):
            return PageType.JOB_LIST_PAGE

        # 6. 其他 51job 页面
        if EHIRE_DOMAIN in url_lower:
            if 'talent' in url_lower or 'home' in url_lower:
                return PageType.HOME_PAGE
            return PageType.OTHER_PAGE

        return PageType.UNKNOWN

    @classmethod
    def is_logged_in(cls, page=None, url: str = '', html: str = '') -> str:
        """
        检测登录状态

        Returns:
            logged_in / expired / unknown
        """
        page_type = cls.detect(page=page, url=url, html=html)

        if page_type == PageType.LOGIN_PAGE:
            return LoginStatus.EXPIRED

        if page_type in (PageType.CANDIDATE_LIST_PAGE,
                         PageType.JOB_LIST_PAGE,
                         PageType.RESUME_DETAIL,
                         PageType.HOME_PAGE):
            return LoginStatus.LOGGED_IN

        if page is not None:
            try:
                features = cls._collect_features(page)
                if features.get('has_user_area') or features.get('has_logout_text'):
                    return LoginStatus.LOGGED_IN
                body = features.get('body_text', '')
                if '登录' in body and ('失效' in body or '过期' in body or '请先登录' in body):
                    return LoginStatus.EXPIRED
            except Exception:
                pass

        return LoginStatus.UNKNOWN

    @staticmethod
    def get_current_job(page) -> str:
        """获取当前选中岗位名称"""
        if page is None:
            return ''
        try:
            return page.evaluate('''() => {
                const items = document.querySelectorAll('.job_name_text');
                for (const el of items) {
                    const menuItem = el.closest('.menu-item_content');
                    if (menuItem && menuItem.classList.contains('menu-item_content_active')) {
                        return el.textContent.trim();
                    }
                }
                return '';
            }''')
        except Exception:
            return ''

    @staticmethod
    def is_candidate_list_page(page) -> bool:
        return PageDetector.detect(page=page) == PageType.CANDIDATE_LIST_PAGE
