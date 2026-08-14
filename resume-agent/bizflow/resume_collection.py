# -*- coding: utf-8 -*-
"""
ResumeCollectionWorkflow - 候选人采集工作流（跨站点通用）。

职责边界（Phase 2C 确认）：
- Workflow 决定"怎么采集"：登录分支、职位切换、滚动循环、去重、终止条件
- 站点知识全部经 SiteAdapter 获取（URL/selector/JS/检测/提取/解析）
- 浏览器操作经 BrowserDriver（Workflow 不碰 Playwright Page 生命周期）
- 浏览器生命周期（启动/连接/重连）由 Worker 壳负责，Workflow 零感知

禁止依赖：浏览器生命周期、页面检测器、跨进程通信、GUI、数据库、任务管理。
"""
import time
from dataclasses import dataclass, field


@dataclass
class CollectionResult:
    """采集结果（保持现有 11 字段语义，to_dict() 兼容旧 GUI）"""

    # ---- 最终结果字段 ----
    success: bool = False
    candidates: list = field(default_factory=list)      # 已采集候选人（含部分失败时保留的数据）
    positions: list = field(default_factory=list)       # 职位列表
    active_position: str = ''
    current_page: int = 1
    total_pages: int = 1

    # ---- 诊断字段 ----
    page_title: str = ''
    page_url: str = ''
    page_type: str = ''
    login_status: str = ''
    error: str = ''

    def to_dict(self) -> dict:
        """兼容层：保证下游 GUI / 跨进程调用方收到原 dict 结构"""
        return {
            'success': self.success,
            'candidates': self.candidates,
            'positions': self.positions,
            'active_position': self.active_position,
            'page_title': self.page_title,
            'page_url': self.page_url,
            'page_type': self.page_type,
            'login_status': self.login_status,
            'current_page': self.current_page,
            'total_pages': self.total_pages,
            'error': self.error,
        }


class ResumeCollectionWorkflow:
    """候选人采集工作流"""

    def __init__(self, driver, site):
        """
        Args:
            driver: BrowserDriver（已就绪的浏览器驱动）
            site:   SiteAdapter（站点适配器）
        """
        self.driver = driver
        self.site = site

    def run(self, switch_job: str = None) -> CollectionResult:
        """执行采集流程，返回 CollectionResult"""
        result = CollectionResult()

        # ---- 诊断信息（属于 Result 数据，读取 driver 基础能力） ----
        try:
            result.page_title = self.driver.title()
        except Exception:
            pass
        try:
            result.page_url = self.driver.url
        except Exception:
            pass
        try:
            result.page_type = self.site.detect_page(self.driver)
        except Exception:
            pass
        result.login_status = self.site.is_logged_in(self.driver)

        # ---- 登录失效：业务终止分支 ----
        if result.login_status == 'expired':
            result.error = self.site.login_expired_error()
            return result

        # ---- 获取职位（可选步骤：失败不致命） ----
        try:
            pos_info = self.site.extract_positions(self.driver)
            result.positions = pos_info.get('positions', [])
            result.active_position = pos_info.get('active', '')
        except Exception:
            pass

        # ---- 切换职位（可选步骤：失败不中断整体流程） ----
        if switch_job:
            try:
                if self.site.switch_job(self.driver, switch_job):
                    time.sleep(5)  # 流程等待页面刷新
                    result.active_position = switch_job
            except Exception:
                pass

        # ---- 获取分页（可选步骤：失败用默认值） ----
        try:
            page_info = self.site.extract_pagination(self.driver)
            result.current_page = page_info.get('currentPage', 1)
            result.total_pages = page_info.get('totalPages', 1)
        except Exception:
            result.current_page = 1
            result.total_pages = 1

        # ---- 滚动采集候选人（核心编排：滚动 + 提取 + 去重 + 终止） ----
        all_candidates = []
        seen = set()
        no_new_count = 0

        try:
            self.driver.mouse_move(600, 400)
            time.sleep(0.5)
        except Exception:
            pass

        for _round in range(100):
            try:
                current = self.site.extract_candidates(self.driver)
            except Exception as e:
                # 采集异常终止：保留已采集数据，明确标记失败
                result.candidates = all_candidates
                result.success = False
                result.error = f'候选人提取失败: {e}'
                return result

            new_count = 0
            for c in current:
                key = c.get('name', '') if isinstance(c, dict) else ''
                if key and key not in seen:
                    seen.add(key)
                    all_candidates.append(c)
                    new_count += 1

            if new_count > 0:
                no_new_count = 0
            else:
                no_new_count += 1

            # 正常终止：连续 3 轮无新候选人
            if no_new_count >= 3:
                break

            try:
                self.driver.scroll_wheel(0, 600)
                time.sleep(1)
            except Exception as e:
                # 滚动异常终止：保留已采集数据，明确标记失败
                result.candidates = all_candidates
                result.success = False
                result.error = f'滚动失败: {e}'
                return result

        # 正常结束
        result.candidates = all_candidates
        result.success = True
        return result
