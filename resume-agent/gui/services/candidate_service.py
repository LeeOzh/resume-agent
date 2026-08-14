# -*- coding: utf-8 -*-
"""
CandidateService - 候选人业务数据管理层（Phase 3B）。

职责：历史查询/external_id 去重过滤/学校过滤/Excel 导出。
不负责：浏览器抓取、AI、下载、任务状态机、GUI 控件、跨进程通信。

结构：AutomationPage -> CandidateService -> Database（学校过滤复用 crawler.school_filter）
"""

from crawler.school_filter import SchoolFilter


class CandidateService:
    def __init__(self, db):
        self.db = db
        self.school_filter = SchoolFilter()
        self.history = {}          # external_id -> 历史处理记录
        self.filter_enabled = False
        self.last_error = ''

    # ==================== 历史关联 / 去重过滤 ====================

    def load_history(self, candidates):
        """按候选人 external_id 查询历史处理记录，填充 self.history"""
        self.history = {}
        if not candidates:
            return
        try:
            from db.models import generate_candidate_external_id
            ext_ids = [
                generate_candidate_external_id(
                    c.get('name', ''),
                    c.get('school', '') or '',
                    c.get('major', '') or '',
                )
                for c in candidates if c.get('name')
            ]
            self.history = self.db.get_candidates_history(ext_ids)
        except Exception as e:
            print(f"加载候选人历史记录失败: {e}")
            self.history = {}

    def filter_by_history(self, candidates):
        """
        基于已加载历史过滤候选人：
        已下载 / AI淘汰 的候选人剔除；失败/有失败原因的保留并展示记录。
        Returns:
            (保留的候选人列表, {'downloaded': n, 'ai_rejected': n})
        """
        if not candidates:
            return [], {'downloaded': 0, 'ai_rejected': 0}
        kept = []
        counts = {'downloaded': 0, 'ai_rejected': 0}
        for c in candidates:
            rec = self._history_record(c)
            status = rec.get('status') if rec else None
            if status == 'downloaded':
                counts['downloaded'] += 1
                continue
            if status == 'ai_rejected':
                counts['ai_rejected'] += 1
                continue
            kept.append(c)
        return kept, counts

    def _history_record(self, candidate):
        """取候选人的历史记录（无则 None）"""
        if not candidate.get('name'):
            return None
        try:
            from db.models import generate_candidate_external_id
            ext_id = generate_candidate_external_id(
                candidate.get('name', ''),
                candidate.get('school', '') or '',
                candidate.get('major', '') or '',
            )
            return self.history.get(ext_id)
        except Exception:
            return None

    def get_history_for(self, candidate) -> dict:
        """返回候选人的历史处理记录展示信息（文本/悬浮提示/颜色）"""
        rec = self._history_record(candidate)
        if not rec:
            return {'text': '', 'tooltip': '', 'color': None}

        status = rec.get('status', '') or ''
        error = rec.get('error_message', '') or ''
        ai_reason = rec.get('ai_reason', '') or ''
        job = rec.get('job_name', '') or ''
        ts = rec.get('updated_at', '') or ''

        if status == 'failed':
            text, color = '失败', (200, 0, 0)
            detail = error or '下载失败'
        elif status == 'downloaded':
            text, color = '已下载', (0, 140, 0)
            detail = '下载成功'
        elif status == 'ai_rejected':
            text, color = 'AI淘汰', (200, 120, 0)
            detail = ai_reason or 'AI评估不通过'
        elif error:
            text, color = '失败', (200, 0, 0)
            detail = error
        else:
            text, color = (status or '有记录'), (120, 120, 120)
            detail = status or ''

        return {
            'text': text,
            'tooltip': f"岗位: {job}\n状态: {detail}\n时间: {ts}",
            'color': color,
        }

    # ==================== 学校过滤（复用 SchoolFilter） ====================

    def set_filter_enabled(self, enabled: bool):
        self.filter_enabled = enabled

    def load_school_list(self, file_path) -> bool:
        """加载学校名单，成功返回 True（UI 提示由页面负责）"""
        self.last_error = ''
        try:
            self.school_filter.load_school_list(file_path)
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def school_count(self) -> int:
        return len(self.school_filter.allowed_schools)

    def is_school_allowed(self, school) -> bool:
        """
        检查学校是否在允许名单中（对齐线上行为）：
        - 未启用过滤 或 学校为空 -> 允许
        - 启用过滤 -> 按名单精确/模糊匹配（名单为空时全部拒绝）
        """
        if not school or not self.filter_enabled:
            return True
        # 强制按名单判断（与页面一致：启用即过滤，不依赖 SchoolFilter.enabled 加载标志）
        self.school_filter.enabled = True
        return self.school_filter.is_allowed_school(school)

    def filter_by_school(self, candidates) -> list:
        return [c for c in candidates if self.is_school_allowed(c.get('school', ''))]

    # ==================== 导出 ====================

    def export_excel(self, results, job_name, download_dir) -> str:
        """导出下载结果 Excel，返回导出文件路径"""
        from datetime import datetime
        from pathlib import Path
        import pandas as pd

        download_dir = Path(download_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_path = download_dir.parent / f"result_{timestamp}.xlsx"

        rows = []
        for r in results:
            status = "成功" if r.get('success') else "失败"
            rows.append({
                "职位": job_name,
                "姓名": r.get('name', ''),
                "页码": r.get('page', ''),
                "下载状态": status,
                "AI评估": "通过" if r.get('ai_pass') is True else (
                    "不通过" if r.get('ai_pass') is False else "未评估"
                ),
                "AI理由": r.get('ai_reason', ''),
                "文件路径": r.get('file_path', ''),
                "错误/原因": r.get('error', ''),
            })
        pd.DataFrame(rows).to_excel(excel_path, index=False, sheet_name="下载结果")
        return str(excel_path)
