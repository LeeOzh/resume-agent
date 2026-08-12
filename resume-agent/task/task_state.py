# -*- coding: utf-8 -*-
"""
任务与候选人状态常量（对应改造方案第 14 / 15 / 20 节）
"""

# Task 状态
TASK_PENDING = 'pending'
TASK_RUNNING = 'running'
TASK_PAUSED = 'paused'
TASK_COMPLETED = 'completed'
TASK_FAILED = 'failed'
TASK_CANCELLED = 'cancelled'

TASK_ACTIVE = (TASK_RUNNING, TASK_PAUSED)

# TaskCandidate 状态机
CAND_PENDING = 'pending'            # 待处理
CAND_PROCESSING = 'processing'      # 正在打开简历/LLM 判断
CAND_AI_REJECTED = 'ai_rejected'    # AI 不通过
CAND_DOWNLOADING = 'downloading'    # 正在下载
CAND_DOWNLOADED = 'downloaded'      # 已下载
CAND_FAILED = 'failed'              # 处理失败

# 终端状态（恢复任务时跳过）
CAND_TERMINAL = (CAND_DOWNLOADED, CAND_AI_REJECTED)
# 可恢复状态
CAND_RECOVERABLE = (CAND_PENDING, CAND_PROCESSING, CAND_FAILED)

# 任务日志事件（改造方案第 17 节）
EVENT_TASK_STARTED = 'task_started'
EVENT_TASK_PAUSED = 'task_paused'
EVENT_TASK_RESUMED = 'task_resumed'
EVENT_TASK_COMPLETED = 'task_completed'
EVENT_PAGE_CHANGED = 'page_changed'
EVENT_CANDIDATE_FOUND = 'candidate_found'
EVENT_CANDIDATE_PROCESSING = 'candidate_processing'
EVENT_RESUME_OPENED = 'resume_opened'
EVENT_AI_ANALYZING = 'ai_analyzing'
EVENT_AI_MATCHED = 'ai_matched'
EVENT_AI_REJECTED = 'ai_rejected'
EVENT_DOWNLOAD_STARTED = 'download_started'
EVENT_DOWNLOAD_SUCCESS = 'download_success'
EVENT_DOWNLOAD_FAILED = 'download_failed'
EVENT_BROWSER_DISCONNECTED = 'browser_disconnected'
EVENT_BROWSER_RECONNECTED = 'browser_reconnected'
EVENT_LOGIN_EXPIRED = 'login_expired'
EVENT_LOGIN_RESTORED = 'login_restored'
