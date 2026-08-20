# -*- coding: utf-8 -*-
"""
微信简历文件目录扫描线程：
扫描聊天文件目录 -> 发现 pdf -> 复制到保存目录 -> 解析姓名 -> 写库 -> 通知界面
"""
import time
from pathlib import Path

from gui.qt_compat import QThread, pyqtSignal

from wechat.wechat_config import load_wechat_config, resolve_save_dir
from wechat.wechat_manager import WeChatManager
from wechat.wechat_parser import parse_candidate_name


class WeChatMonitorThread(QThread):
    """后台扫描线程（不依赖微信 UI，扫描本地聊天文件目录）"""

    new_record = pyqtSignal(dict)      # 新记录（含 status/file_path 等）
    log_message = pyqtSignal(str)
    status_changed = pyqtSignal(str)   # scanning / stopped / error

    def __init__(self, db, group_name, parent=None):
        super().__init__(parent)
        self.db = db
        self.group_name = group_name          # 目录/月份标识，如 2026-08
        self._stop = False
        self._seen_pairs = set()              # 历史记录：目录+文件名（重启不重复处理）
        self._manager = WeChatManager()

    def stop_monitor(self):
        """请求停止（线程在下个轮询点退出）"""
        self._stop = True

    def run(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        config = load_wechat_config()
        poll_interval = max(1, float(config.get("poll_interval", 2.0)))
        save_dir = resolve_save_dir(config)
        self._preload_seen()
        try:
            if not self._manager.connect():
                self.log_message.emit(
                    f"微信目录检测失败: {self._manager.last_error or '未知错误'}"
                )
                self.status_changed.emit('error')
                return
            self.log_message.emit(
                f"开始扫描聊天文件目录: {self._manager.chatfile_folder}"
            )
            self.status_changed.emit('scanning')
            while not self._stop:
                self._scan_once(save_dir)
                for _ in range(10):
                    if self._stop:
                        break
                    time.sleep(poll_interval / 10)
        except Exception as e:
            self.log_message.emit(f"扫描异常: {e}")
            self.status_changed.emit('error')
        finally:
            if not self._stop:
                self._stop = True
            self.status_changed.emit('stopped')

    def _preload_seen(self):
        """启动时从数据库加载历史记录，避免重复处理同一批文件"""
        try:
            records = self.db.get_wechat_records(limit=5000)
            for rec in records:
                key = (str(rec.get('group_name', '')), str(rec.get('file_name', '')))
                self._seen_pairs.add(key)
        except Exception:
            pass

    def _scan_once(self, save_dir):
        try:
            files = self._manager.scan_pdf_files()
        except Exception:
            return
        for f in files:
            if self._stop:
                return
            try:
                self._handle_file(f, save_dir)
            except Exception as e:
                self.log_message.emit(f"处理文件异常: {e}")

    def _handle_file(self, f, save_dir):
        file_name = str(f.get('file_name', '') or '').strip()
        file_name = Path(file_name).name
        if not file_name:
            return
        if Path(file_name).suffix.lower() != '.pdf':
            return
        # 只处理目标公司前缀开头的简历文件（如 广州海颐-xxx），其它忽略
        config = load_wechat_config()
        prefixes = config.get("company_prefixes") or []
        if not any(str(file_name).startswith(p) for p in prefixes if p):
            return

        # 数据库中已存在的文件不再重复处理
        pair = (str(self.group_name), file_name)
        if pair in self._seen_pairs:
            return
        self._seen_pairs.add(pair)

        src = Path(f.get('file_path', ''))
        if not src.is_file():
            return

        self.log_message.emit(f"[{self.group_name}] 发现简历文件: {file_name}")

        # 复制到保存目录
        try:
            saved_path = self._manager.copy_file(src, Path(save_dir), file_name)
        except Exception as e:
            saved_path = None
            self.log_message.emit(f"复制文件失败: {e}")
        if not saved_path:
            self._save_record(
                self.group_name, file_name, '.pdf', '', '',
                'download_failed', f'复制文件失败（源: {src}）'
            )
            return

        # 解析姓名
        name = parse_candidate_name(file_name, config.get("company_prefixes"))
        if name:
            status, error = 'downloaded', ''
            self.log_message.emit(f"已复制并解析姓名: {file_name} -> {name}")
        else:
            status, error = 'parse_failed', '文件名未能解析出姓名，请手动补充'
            self.log_message.emit(f"已复制但姓名解析失败: {file_name}")

        record_id = self._save_record(
            self.group_name, file_name, '.pdf', name, '', status, error,
            file_path=str(saved_path),
        )
        self.new_record.emit({
            'id': record_id,
            'group_name': str(self.group_name),
            'file_name': file_name,
            'candidate_name': name,
            'file_ext': '.pdf',
            'file_path': str(saved_path),
            'sender': '',
            'status': status,
            'error_message': error,
        })

    def _save_record(self, group_name, file_name, ext, name, sender,
                     status, error, file_path=''):
        try:
            return self.db.add_wechat_record(
                group_name=group_name,
                file_name=file_name,
                candidate_name=name,
                file_ext=ext,
                file_path=file_path,
                sender=sender,
                status=status,
                error_message=error,
            )
        except Exception as e:
            self.log_message.emit(f"写入数据库失败: {e}")
            return None
