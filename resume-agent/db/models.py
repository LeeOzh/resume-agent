# -*- coding: utf-8 -*-
"""
数据库模型定义
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Job:
    """岗位表"""
    id: Optional[int] = None
    name: str = ''                      # 岗位名称
    page_url: str = ''                  # 页面URL
    is_active: bool = False             # 是否当前活跃
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Task:
    """任务表 - 代表一次完整的岗位候选人AI筛选/下载运行"""
    id: Optional[int] = None
    job_id: Optional[int] = None        # 关联岗位
    job_name: str = ''                  # 岗位名称快照
    status: str = 'pending'             # pending/running/paused/completed/failed/cancelled
    
    # AI配置快照（任务创建时保存，运行期间不变）
    ai_enabled: bool = False
    ai_api_key: str = ''
    ai_match_description: str = ''
    
    # 下载配置
    download_dir: str = ''
    download_all_pages: bool = False
    
    # 统计信息
    total_candidates: int = 0           # 总候选人数
    processed_count: int = 0            # 已处理数
    success_count: int = 0              # 成功数
    failed_count: int = 0               # 失败数
    ai_pass_count: int = 0              # AI通过数
    ai_fail_count: int = 0              # AI不通过数
    
    # 页面信息
    current_page: int = 1
    total_pages: int = 1
    
    # 结果文件
    excel_path: str = ''                # 导出的Excel路径
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class TaskCandidate:
    """任务候选人表"""
    id: Optional[int] = None
    task_id: int = 0                    # 关联任务
    candidate_external_id: str = ''     # 候选人唯一标识（姓名+学校+专业的hash）
    
    # 候选人信息
    name: str = ''
    school: str = ''
    major: str = ''
    education: str = ''
    
    # 页面定位
    page_num: int = 1
    
    # AI筛选结果
    ai_processed: bool = False          # 是否已AI评估
    ai_pass: Optional[bool] = None      # AI是否通过
    ai_score: float = 0.0               # AI评分
    ai_reason: str = ''                 # AI理由
    
    # 下载状态
    download_status: str = 'pending'    # pending/downloading/success/failed/skipped
    file_path: str = ''                 # 下载文件路径
    error_message: str = ''             # 错误信息
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class TaskLog:
    """任务日志表"""
    id: Optional[int] = None
    task_id: int = 0                    # 关联任务
    level: str = 'info'                 # info/warning/error
    message: str = ''
    created_at: Optional[datetime] = None


def generate_candidate_external_id(name: str, school: str = '', major: str = '') -> str:
    """生成候选人唯一标识"""
    import hashlib
    # 使用姓名+学校+专业生成唯一ID
    raw = f"{name}|{school}|{major}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]