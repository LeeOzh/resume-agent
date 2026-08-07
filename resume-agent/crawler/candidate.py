# -*- coding: utf-8 -*-
from playwright.sync_api import Page
import re


class CandidateParser:
    """解析候选人列表"""

    def __init__(self, page: Page):
        self.page = page

    def parse_list(self) -> list:
        """解析候选人列表，返回候选人信息
        
        返回格式:
        [
            {
                "name": "候选人姓名",
                "url": "简历详情页URL",
                "id": "候选人ID",
                "element": playwright.ElementHandle  # 用于后续点击操作
            }
        ]
        """
        candidates = []

        # 根据实际HTML结构，候选人列表在 class="list" 的div中
        # 每个候选人是 class="item virtual_list" 的div
        items = self.page.query_selector_all('.item.virtual_list')

        if not items:
            # 备用选择器
            items = self.page.query_selector_all('[class*="item"][class*="virtual_list"]')

        for index, item in enumerate(items):
            candidate = self._extract_candidate(item, index)
            if candidate:
                candidates.append(candidate)

        return candidates

    def _extract_candidate(self, element, index: int) -> dict:
        """从元素中提取候选人信息"""
        try:
            # 提取候选人姓名 - 在 class="detail" -> class="firstline" -> class="name" 中
            name_el = element.query_selector('.detail .firstline .name')
            if not name_el:
                name_el = element.query_selector('.name')
            
            name = ""
            if name_el:
                name = name_el.inner_text().strip()

            # 提取求职意向
            apply_info = ""
            apply_el = element.query_selector('.apply_news')
            if apply_el:
                apply_info = apply_el.inner_text().strip()

            # 提取技能标签
            skills = []
            skill_els = element.query_selector_all('.search_tag .skill_label, .labelHighLight')
            for skill_el in skill_els[:5]:  # 限制数量
                skill_text = skill_el.inner_text().strip()
                if skill_text:
                    skills.append(skill_text)

            # 提取活跃状态
            active = ""
            active_el = element.query_selector('.active')
            if active_el:
                active = active_el.inner_text().strip()

            # 生成一个ID
            candidate_id = f"candidate_{index + 1}"

            if name:
                return {
                    "name": name,
                    "url": "",  # 需要点击后才能获取
                    "id": candidate_id,
                    "apply_info": apply_info,
                    "skills": skills,
                    "active": active,
                    "element": element  # 保存元素引用，用于后续点击
                }
        except Exception as e:
            print(f"提取候选人信息失败: {e}")
        return None

    def debug_page_structure(self) -> dict:
        """调试模式：输出页面结构信息"""
        result = {
            "title": self.page.title(),
            "url": self.page.url,
            "candidate_count": 0,
            "links": [],
            "tables": [],
            "lists": []
        }

        # 统计候选人数量
        items = self.page.query_selector_all('.item.virtual_list')
        result["candidate_count"] = len(items)

        # 获取所有链接
        links = self.page.query_selector_all("a[href]")
        for link in links[:30]:
            text = link.inner_text().strip()[:50]
            href = link.get_attribute("href")
            if text and href:
                result["links"].append({"text": text, "href": href})

        # 获取表格
        tables = self.page.query_selector_all("table")
        for i, table in enumerate(tables[:5]):
            rows = table.query_selector_all("tr")
            result["tables"].append({
                "index": i,
                "rows": len(rows)
            })

        # 获取列表
        lists = self.page.query_selector_all("ul, ol")
        for i, lst in enumerate(lists[:5]):
            items = lst.query_selector_all("li")
            result["lists"].append({
                "index": i,
                "items": len(items)
            })

        return result
