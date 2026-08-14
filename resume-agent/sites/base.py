# -*- coding: utf-8 -*-
"""
SiteAdapter - 站点适配器抽象基类。

职责边界（Phase 2 讨论确认）：
- 提供站点能力：URL / 选择器 / 页面检测 / 提取 / 解析
- 不含流程编排：循环、等待、重试、去重属于 Workflow
- 方法粒度：一次性站点操作（如 switch_job），不包含"点击后验证"这类编排

Workflow 只依赖本抽象，不依赖具体站点实现（依赖倒置）。
"""
from abc import ABC, abstractmethod


class SiteAdapter(ABC):
    """站点适配器基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """站点名，如 '51job'"""

    @property
    @abstractmethod
    def domain(self) -> str:
        """站点域名特征，如 '51job.com'"""

    @abstractmethod
    def url(self, name: str) -> str:
        """逻辑名 -> URL（如 url('talent_management')）"""

    @abstractmethod
    def selector(self, key: str) -> str:
        """逻辑名 -> CSS 选择器（如 selector('job_menu')）"""

    @abstractmethod
    def detect_page(self, driver) -> str:
        """检测当前页面类型，返回通用页面类型字符串（如 'CANDIDATE_LIST_PAGE'）"""

    @abstractmethod
    def is_logged_in(self, driver) -> str:
        """
        检测当前站点登录状态，返回 'logged_in' / 'expired' / 'unknown'。
        登录状态的 DOM/URL 判断属于站点知识，由 Adapter 实现。
        """

    @abstractmethod
    def login_expired_error(self) -> str:
        """登录失效时给用户的错误文案（站点知识，Workflow 不写死站点名）"""

    # ---------------- 站点能力（一次性操作，不含编排） ----------------

    @abstractmethod
    def extract_positions(self, driver) -> dict:
        """提取职位列表，返回 {'positions': [...], 'active': str}"""

    @abstractmethod
    def switch_job(self, driver, job_name: str) -> bool:
        """切换到指定职位（定位并点击），返回是否成功"""

    @abstractmethod
    def go_to_page(self, driver, page_num: int) -> bool:
        """定位到指定页码（站点特有分页 DOM），返回是否成功"""

    @abstractmethod
    def get_current_job(self, driver) -> str:
        """获取当前选中职位名（站点特有 DOM 判断），无则返回空串"""

    @abstractmethod
    def extract_pagination(self, driver) -> dict:
        """提取当前页码与总页数，返回 {'currentPage': int, 'totalPages': int}"""

    @abstractmethod
    def extract_candidates(self, driver) -> list:
        """从页面提取候选人原始数据（可含站点 JS，不含滚动/去重）"""

    @abstractmethod
    def parse_candidates(self, data: list) -> list:
        """原始数据 -> 统一候选人结构列表（清洗/标准化）"""

    # ---------------- 下载能力（站点特有交互，流程编排归 Workflow） ----------------

    @abstractmethod
    def has_next_page(self, driver) -> bool:
        """检查是否有下一页（站点分页 DOM）"""

    @abstractmethod
    def go_to_next_page(self, driver) -> bool:
        """点击下一页并等待翻页生效（站点交互 + 等待策略）"""

    @abstractmethod
    def scroll_to_pagination(self, driver):
        """滚动到分页控件（站点分页 selector + 兜底滚轮）"""

    @abstractmethod
    def find_candidate_by_name(self, driver, name: str):
        """按姓名定位候选人元素（站点列表 DOM），无则返回 None"""

    @abstractmethod
    def find_name_element(self, driver, name: str):
        """按姓名定位候选人姓名字素（站点列表 DOM），无则返回 None"""

    @abstractmethod
    def find_attachment_button(self, driver):
        """定位简历附件按钮（站点详情 DOM），无则返回 None"""

    @abstractmethod
    def find_download_button(self, driver):
        """定位下载按钮（站点附件/详情 DOM），无则返回 None"""

    @abstractmethod
    def extract_resume_text(self, driver) -> str:
        """读取简历详情页文本（站点详情 DOM），失败返回空串"""

    @abstractmethod
    def scroll_to_top(self, driver):
        """滚动到列表顶部并重置滚动容器（站点列表 DOM）"""
