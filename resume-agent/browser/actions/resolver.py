# -*- coding: utf-8 -*-
"""
TargetResolver - 把逻辑 target 解析成实际 locator。

职责（Phase 2 讨论确认）：
- 不拥有站点选择器（selector 唯一来源是 SiteAdapter），只回答"向谁询问"
- 用 CSS 特征启发式区分"逻辑名"与"原始 CSS 选择器"：
    带 CSS 特征开头（. # [ : > 等）→ 原始 selector，直接透传（渐进迁移兼容）
    否则 → 逻辑名，必须能从 SiteAdapter.selector() 查到，查不到抛清晰异常
"""
import re


# CSS 选择器特征前缀：点 class / 井号 id / 中括号属性 / 冒号伪类 / 子代 > / 通配 *
_CSS_PREFIX_RE = re.compile(r'^[.#\[:>*]')


class TargetResolver:
    def __init__(self, site=None):
        """
        Args:
            site: SiteAdapter 实例（Phase 2B 起必传；传入 None 时退化为纯透传）
        """
        self.site = site

    def resolve(self, target: str) -> str:
        """
        解析 target：
        - 原始 CSS 选择器（. # [ : > 等开头）→ 原样返回
        - 逻辑名 → site.selector(target)；site 为空或查不到时抛清晰异常
        """
        if not target:
            return target
        if _CSS_PREFIX_RE.match(target):
            return target
        if self.site is None:
            raise KeyError(
                f"逻辑目标 '{target}' 无法解析：TargetResolver 未注入 SiteAdapter。"
                "若是 CSS 选择器请以 . # [ 等开头"
            )
        try:
            return self.site.selector(target)
        except KeyError:
            raise KeyError(
                f"未知逻辑目标 '{target}'：site={getattr(self.site, 'name', '?')}。"
                "若是 CSS 选择器请以 . # [ 等开头，否则请检查逻辑名是否正确"
            )
