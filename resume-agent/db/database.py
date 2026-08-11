# -*- coding: utf-8 -*-
"""
数据库操作类
"""
import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

from .models import Job, Task, TaskCandidate, TaskLog, generate_candidate_external_id


def _get_base_dir():
    """获取基础目录（兼容打包后的路径）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


class Database:
    """SQLite数据库操作类"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(_get_base_dir() / "data" / "resume_agent.db")
        
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()
    
    def _ensure_dir(self):
        """确保数据库目录存在"""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            # 如果创建目录失败，使用临时目录
            import tempfile
            self.db_path = str(Path(tempfile.gettempdir()) / "resume_agent.db")
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    
    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        try:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    page_url TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    job_name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    
                    ai_enabled INTEGER DEFAULT 0,
                    ai_api_key TEXT DEFAULT '',
                    ai_match_description TEXT DEFAULT '',
                    
                    download_dir TEXT DEFAULT '',
                    download_all_pages INTEGER DEFAULT 0,
                    
                    total_candidates INTEGER DEFAULT 0,
                    processed_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    ai_pass_count INTEGER DEFAULT 0,
                    ai_fail_count INTEGER DEFAULT 0,
                    
                    current_page INTEGER DEFAULT 1,
                    total_pages INTEGER DEFAULT 1,
                    
                    excel_path TEXT DEFAULT '',
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );
                
                CREATE TABLE IF NOT EXISTS task_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    candidate_external_id TEXT NOT NULL,
                    
                    name TEXT NOT NULL,
                    school TEXT DEFAULT '',
                    major TEXT DEFAULT '',
                    education TEXT DEFAULT '',
                    
                    page_num INTEGER DEFAULT 1,
                    
                    ai_processed INTEGER DEFAULT 0,
                    ai_pass INTEGER,
                    ai_score REAL DEFAULT 0.0,
                    ai_reason TEXT DEFAULT '',
                    
                    download_status TEXT DEFAULT 'pending',
                    file_path TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (task_id) REFERENCES tasks(id),
                    UNIQUE(task_id, candidate_external_id)
                );
                
                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    level TEXT DEFAULT 'info',
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks(job_id);
                CREATE INDEX IF NOT EXISTS idx_task_candidates_task_id ON task_candidates(task_id);
                CREATE INDEX IF NOT EXISTS idx_task_candidates_external_id ON task_candidates(candidate_external_id);
                CREATE INDEX IF NOT EXISTS idx_task_candidates_status ON task_candidates(download_status);
            ''')
            conn.commit()
        finally:
            conn.close()
    
    # ==================== Jobs ====================
    
    def sync_jobs(self, positions: List[dict]) -> List[Job]:
        """同步岗位列表"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            jobs = []
            
            for pos in positions:
                name = pos.get('name', '').strip()
                if not name:
                    continue
                
                is_active = pos.get('active', False)
                
                # 尝试更新
                cursor = conn.execute(
                    "UPDATE jobs SET is_active=?, updated_at=? WHERE name=?",
                    (1 if is_active else 0, now, name)
                )
                
                if cursor.rowcount == 0:
                    # 不存在则插入
                    cursor = conn.execute(
                        "INSERT INTO jobs (name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (name, 1 if is_active else 0, now, now)
                    )
                
                job_id = cursor.lastrowid if cursor.rowcount == 0 else None
                if job_id is None:
                    row = conn.execute("SELECT id FROM jobs WHERE name=?", (name,)).fetchone()
                    job_id = row['id'] if row else None
                
                jobs.append(Job(
                    id=job_id,
                    name=name,
                    is_active=is_active,
                    updated_at=now
                ))
            
            # 将不在列表中的岗位设为非活跃
            active_names = [p.get('name', '') for p in positions]
            if active_names:
                placeholders = ','.join(['?' for _ in active_names])
                conn.execute(
                    f"UPDATE jobs SET is_active=0, updated_at=? WHERE name NOT IN ({placeholders})",
                    [now] + active_names
                )
            
            conn.commit()
            return jobs
        finally:
            conn.close()
    
    def get_active_job(self) -> Optional[Job]:
        """获取当前活跃岗位"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE is_active=1 LIMIT 1").fetchone()
            if row:
                return Job(
                    id=row['id'],
                    name=row['name'],
                    page_url=row['page_url'],
                    is_active=bool(row['is_active']),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
            return None
        finally:
            conn.close()
    
    def get_job_by_name(self, name: str) -> Optional[Job]:
        """根据名称获取岗位"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE name=?", (name,)).fetchone()
            if row:
                return Job(
                    id=row['id'],
                    name=row['name'],
                    page_url=row['page_url'],
                    is_active=bool(row['is_active']),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
            return None
        finally:
            conn.close()
    
    # ==================== Tasks ====================
    
    def create_task(self, job_name: str, ai_config: dict, download_dir: str, 
                    download_all_pages: bool = False, total_candidates: int = 0) -> Task:
        """创建新任务"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            
            # 获取job_id
            job = self.get_job_by_name(job_name)
            job_id = job.id if job else None
            
            # AI配置快照
            ai_enabled = ai_config.get('enabled', False) if ai_config else False
            ai_api_key = ai_config.get('api_key', '') if ai_config else ''
            ai_match_desc = ai_config.get('match_description', '') if ai_config else ''
            
            cursor = conn.execute('''
                INSERT INTO tasks (
                    job_id, job_name, status,
                    ai_enabled, ai_api_key, ai_match_description,
                    download_dir, download_all_pages,
                    total_candidates, current_page, total_pages,
                    created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            ''', (
                job_id, job_name,
                1 if ai_enabled else 0, ai_api_key, ai_match_desc,
                download_dir, 1 if download_all_pages else 0,
                total_candidates, now, now
            ))
            
            task_id = cursor.lastrowid
            
            # 记录日志
            self.add_task_log(task_id, 'info', f'任务创建: {job_name}')
            if ai_enabled:
                self.add_task_log(task_id, 'info', f'AI筛选已启用')
            
            conn.commit()
            
            return Task(
                id=task_id,
                job_id=job_id,
                job_name=job_name,
                status='pending',
                ai_enabled=ai_enabled,
                ai_api_key=ai_api_key,
                ai_match_description=ai_match_desc,
                download_dir=download_dir,
                download_all_pages=download_all_pages,
                total_candidates=total_candidates,
                created_at=now,
                updated_at=now
            )
        finally:
            conn.close()
    
    def get_task(self, task_id: int) -> Optional[Task]:
        """获取任务"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row:
                return self._row_to_task(row)
            return None
        finally:
            conn.close()
    
    def get_unfinished_tasks(self) -> List[Task]:
        """获取未完成的任务（running或paused）"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN ('running', 'paused') ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_task(row) for row in rows]
        finally:
            conn.close()
    
    def update_task_status(self, task_id: int, status: str):
        """更新任务状态"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            if status == 'completed':
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=?, completed_at=? WHERE id=?",
                    (status, now, now, task_id)
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                    (status, now, task_id)
                )
            conn.commit()
        finally:
            conn.close()
    
    def update_task_progress(self, task_id: int, **kwargs):
        """更新任务进度"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            allowed_fields = [
                'total_candidates', 'processed_count', 'success_count', 
                'failed_count', 'ai_pass_count', 'ai_fail_count',
                'current_page', 'total_pages', 'excel_path'
            ]
            
            updates = []
            values = []
            for field_name, value in kwargs.items():
                if field_name in allowed_fields:
                    updates.append(f"{field_name}=?")
                    values.append(value)
            
            if updates:
                updates.append("updated_at=?")
                values.append(now)
                values.append(task_id)
                
                sql = f"UPDATE tasks SET {', '.join(updates)} WHERE id=?"
                conn.execute(sql, values)
                conn.commit()
        finally:
            conn.close()
    
    def _row_to_task(self, row) -> Task:
        """将数据库行转换为Task对象"""
        return Task(
            id=row['id'],
            job_id=row['job_id'],
            job_name=row['job_name'],
            status=row['status'],
            ai_enabled=bool(row['ai_enabled']),
            ai_api_key=row['ai_api_key'] or '',
            ai_match_description=row['ai_match_description'] or '',
            download_dir=row['download_dir'] or '',
            download_all_pages=bool(row['download_all_pages']),
            total_candidates=row['total_candidates'],
            processed_count=row['processed_count'],
            success_count=row['success_count'],
            failed_count=row['failed_count'],
            ai_pass_count=row['ai_pass_count'],
            ai_fail_count=row['ai_fail_count'],
            current_page=row['current_page'],
            total_pages=row['total_pages'],
            excel_path=row['excel_path'] or '',
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            completed_at=row['completed_at']
        )
    
    # ==================== Task Candidates ====================
    
    def add_candidate(self, task_id: int, candidate: dict) -> TaskCandidate:
        """添加候选人到任务"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            name = candidate.get('name', '')
            school = candidate.get('school', '')
            major = candidate.get('major', '')
            education = candidate.get('education', '')
            page_num = candidate.get('page', 1)
            
            ext_id = generate_candidate_external_id(name, school, major)
            
            # 尝试插入，如果已存在则忽略
            try:
                conn.execute('''
                    INSERT INTO task_candidates (
                        task_id, candidate_external_id,
                        name, school, major, education,
                        page_num, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (task_id, ext_id, name, school, major, education, page_num, now, now))
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # 已存在，忽略
            
            return TaskCandidate(
                task_id=task_id,
                candidate_external_id=ext_id,
                name=name,
                school=school,
                major=major,
                education=education,
                page_num=page_num
            )
        finally:
            conn.close()
    
    def add_candidates_batch(self, task_id: int, candidates: List[dict]) -> int:
        """批量添加候选人"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            added = 0
            
            for candidate in candidates:
                name = candidate.get('name', '')
                school = candidate.get('school', '')
                major = candidate.get('major', '')
                education = candidate.get('education', '')
                page_num = candidate.get('page', 1)
                
                ext_id = generate_candidate_external_id(name, school, major)
                
                try:
                    conn.execute('''
                        INSERT INTO task_candidates (
                            task_id, candidate_external_id,
                            name, school, major, education,
                            page_num, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (task_id, ext_id, name, school, major, education, page_num, now, now))
                    added += 1
                except sqlite3.IntegrityError:
                    pass
            
            conn.commit()
            return added
        finally:
            conn.close()
    
    def get_candidate_by_external_id(self, task_id: int, external_id: str) -> Optional[TaskCandidate]:
        """根据外部ID获取候选人"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM task_candidates WHERE task_id=? AND candidate_external_id=?",
                (task_id, external_id)
            ).fetchone()
            if row:
                return self._row_to_candidate(row)
            return None
        finally:
            conn.close()
    
    def get_pending_candidates(self, task_id: int) -> List[TaskCandidate]:
        """获取待处理的候选人"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM task_candidates WHERE task_id=? AND download_status='pending' ORDER BY page_num, id",
                (task_id,)
            ).fetchall()
            return [self._row_to_candidate(row) for row in rows]
        finally:
            conn.close()
    
    def get_task_candidates(self, task_id: int) -> List[TaskCandidate]:
        """获取任务的所有候选人"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM task_candidates WHERE task_id=? ORDER BY page_num, id",
                (task_id,)
            ).fetchall()
            return [self._row_to_candidate(row) for row in rows]
        finally:
            conn.close()
    
    def update_candidate_ai_result(self, task_id: int, external_id: str, 
                                    ai_pass: bool, ai_reason: str, ai_score: float = 0.0):
        """更新候选人AI评估结果"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            conn.execute('''
                UPDATE task_candidates 
                SET ai_processed=1, ai_pass=?, ai_reason=?, ai_score=?, updated_at=?
                WHERE task_id=? AND candidate_external_id=?
            ''', (1 if ai_pass else 0, ai_reason, ai_score, now, task_id, external_id))
            conn.commit()
        finally:
            conn.close()
    
    def update_candidate_download_status(self, task_id: int, external_id: str,
                                         status: str, file_path: str = '', error_message: str = ''):
        """更新候选人下载状态"""
        conn = self._get_conn()
        try:
            now = datetime.now()
            conn.execute('''
                UPDATE task_candidates 
                SET download_status=?, file_path=?, error_message=?, updated_at=?
                WHERE task_id=? AND candidate_external_id=?
            ''', (status, file_path, error_message, now, task_id, external_id))
            conn.commit()
        finally:
            conn.close()
    
    def _row_to_candidate(self, row) -> TaskCandidate:
        """将数据库行转换为TaskCandidate对象"""
        return TaskCandidate(
            id=row['id'],
            task_id=row['task_id'],
            candidate_external_id=row['candidate_external_id'],
            name=row['name'],
            school=row['school'] or '',
            major=row['major'] or '',
            education=row['education'] or '',
            page_num=row['page_num'],
            ai_processed=bool(row['ai_processed']),
            ai_pass=bool(row['ai_pass']) if row['ai_pass'] is not None else None,
            ai_score=row['ai_score'] or 0.0,
            ai_reason=row['ai_reason'] or '',
            download_status=row['download_status'],
            file_path=row['file_path'] or '',
            error_message=row['error_message'] or '',
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    # ==================== Task Logs ====================
    
    def add_task_log(self, task_id: int, level: str, message: str):
        """添加任务日志"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO task_logs (task_id, level, message, created_at) VALUES (?, ?, ?, ?)",
                (task_id, level, message, datetime.now())
            )
            conn.commit()
        finally:
            conn.close()
    
    def get_task_logs(self, task_id: int, limit: int = 100) -> List[TaskLog]:
        """获取任务日志"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM task_logs WHERE task_id=? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit)
            ).fetchall()
            return [TaskLog(
                id=row['id'],
                task_id=row['task_id'],
                level=row['level'],
                message=row['message'],
                created_at=row['created_at']
            ) for row in rows]
        finally:
            conn.close()
    
    # ==================== 统计 ====================
    
    def get_task_stats(self, task_id: int) -> dict:
        """获取任务统计信息"""
        conn = self._get_conn()
        try:
            row = conn.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN download_status='success' THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN download_status='failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN download_status='skipped' THEN 1 ELSE 0 END) as skipped,
                    SUM(CASE WHEN ai_processed=1 AND ai_pass=1 THEN 1 ELSE 0 END) as ai_pass,
                    SUM(CASE WHEN ai_processed=1 AND ai_pass=0 THEN 1 ELSE 0 END) as ai_fail
                FROM task_candidates WHERE task_id=?
            ''', (task_id,)).fetchone()
            
            return {
                'total': row['total'] or 0,
                'success': row['success'] or 0,
                'failed': row['failed'] or 0,
                'skipped': row['skipped'] or 0,
                'ai_pass': row['ai_pass'] or 0,
                'ai_fail': row['ai_fail'] or 0
            }
        finally:
            conn.close()