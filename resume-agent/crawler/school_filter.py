# -*- coding: utf-8 -*-
"""
学校名单过滤模块
用于过滤不在可录用学校名单中的候选人
"""
import pandas as pd
from pathlib import Path


class SchoolFilter:
    """学校名单过滤器"""

    def __init__(self, school_list_path=None):
        """
        初始化学校过滤器

        Args:
            school_list_path: 学校名单Excel文件路径
        """
        self.school_list_path = school_list_path
        self.allowed_schools = set()
        self.school_info = {}  # 学校名称 -> 详细信息
        self.enabled = False

        if school_list_path and Path(school_list_path).exists():
            self.load_school_list(school_list_path)

    def load_school_list(self, file_path):
        """
        加载学校名单

        Args:
            file_path: Excel文件路径
        """
        try:
            df = pd.read_excel(file_path)

            # 清理学校名称（去除空格等）
            for _, row in df.iterrows():
                school_name = str(row.get('学校名称', '')).strip()
                if school_name and school_name != 'nan':
                    self.allowed_schools.add(school_name)
                    self.school_info[school_name] = {
                        '排名': row.get('2026排名', ''),
                        '是否985': row.get('是否985', ''),
                        '是否211': row.get('是否211', ''),
                        '是否双一流': row.get('是否双一流', ''),
                        '省市': row.get('省市', ''),
                    }

            self.enabled = True
            print(f"已加载 {len(self.allowed_schools)} 所可录用学校")

        except Exception as e:
            print(f"加载学校名单失败: {e}")
            self.enabled = False

    def is_allowed_school(self, school_name):
        """
        检查学校是否在可录用名单中

        Args:
            school_name: 学校名称

        Returns:
            bool: 是否允许录用
        """
        if not self.enabled:
            return True  # 未启用过滤，允许所有

        if not school_name:
            return True  # 没有学校信息，允许（可能是社招）

        # 清理学校名称
        school_name = str(school_name).strip()

        # 精确匹配
        if school_name in self.allowed_schools:
            return True

        # 模糊匹配（处理"XX大学XX学院"等情况）
        for allowed in self.allowed_schools:
            if allowed in school_name or school_name in allowed:
                return True

        return False

    def get_school_info(self, school_name):
        """
        获取学校详细信息

        Args:
            school_name: 学校名称

        Returns:
            dict: 学校信息，未找到返回None
        """
        school_name = str(school_name).strip()
        return self.school_info.get(school_name)

    def filter_candidates(self, candidates):
        """
        过滤候选人列表

        Args:
            candidates: 候选人列表，每个候选人是dict，包含name, school等字段

        Returns:
            list: 过滤后的候选人列表
        """
        if not self.enabled:
            return candidates

        filtered = []
        removed_count = 0

        for candidate in candidates:
            school = candidate.get('school', '')
            if self.is_allowed_school(school):
                filtered.append(candidate)
            else:
                removed_count += 1

        if removed_count > 0:
            print(f"学校过滤: 已移除 {removed_count} 名不在名单中的候选人")

        return filtered

    def get_filter_summary(self):
        """获取过滤器摘要信息"""
        return {
            'enabled': self.enabled,
            'school_count': len(self.allowed_schools),
            'school_list_path': str(self.school_list_path) if self.school_list_path else None
        }