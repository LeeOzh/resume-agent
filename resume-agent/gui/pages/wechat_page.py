# -*- coding: utf-8 -*-
"""
微信简历解析页面（V1 极简功能）

流程：检测微信安装位置 -> 定位聊天文件目录 -> 扫描 PDF 简历文件
      -> 解析姓名 -> SQLite -> Excel

说明：
- 不依赖微信界面自动化（微信 4.1.x 控件树不可用），直接解析本地聊天文件目录；
- 扫描由后台线程执行（wechat/wechat_monitor.py），不阻塞界面；
- 只处理 pdf 文件；文件名格式：广州海颐-xxxxx工程师-姓名.pdf。
"""
import sys
import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QTextEdit, QMessageBox, QInputDialog, QGroupBox,
)
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, TableWidget,
    InfoBadge, InfoLevel, FluentIcon,
)


if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent.parent


STATUS_LABELS = {
    'downloaded': '已下载',
    'parse_failed': '解析失败',
    'download_failed': '下载失败',
}


class WeChatPage(QWidget):
    """微信简历解析页面"""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.db = main.db
        self.monitor = None
        self.manager = None
        self.setup_ui()
        self._reload_records()

    # ---------------- 界面 ----------------

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(12)

        # 检测与扫描控制
        control_group = QGroupBox("微信简历解析")
        control_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        self.connect_btn = PushButton("检测微信目录")
        self.connect_btn.setIcon(FluentIcon.CONNECT)
        self.connect_btn.clicked.connect(self.connect_wechat)
        row1.addWidget(self.connect_btn)

        self.conn_badge = InfoBadge("未检测", None, InfoLevel.INFOAMTION)
        row1.addWidget(self.conn_badge)

        self.pick_dir_btn = PushButton("手动选择目录")
        self.pick_dir_btn.clicked.connect(self.pick_chatfile_dir)
        row1.addWidget(self.pick_dir_btn)
        row1.addStretch()
        control_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("扫描范围:"))
        self.session_combo = ComboBox()
        self.session_combo.setMinimumWidth(180)
        self.session_combo.addItem("全部")
        self.session_combo.setPlaceholderText("全部月份")
        row2.addWidget(self.session_combo, 0)

        row2.addWidget(QLabel("聊天文件目录:"))
        self.dir_label = QLabel("未检测")
        self.dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row2.addWidget(self.dir_label, 1)
        control_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.start_btn = PrimaryPushButton("扫描解析")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.start_btn.clicked.connect(self.start_listen)
        row3.addWidget(self.start_btn)

        self.stop_btn = PushButton("停止扫描")
        self.stop_btn.setIcon(FluentIcon.CANCEL)
        self.stop_btn.clicked.connect(self.stop_listen)
        self.stop_btn.setEnabled(False)
        row3.addWidget(self.stop_btn)

        self.listen_badge = InfoBadge("未扫描", None, InfoLevel.INFOAMTION)
        row3.addWidget(self.listen_badge)
        row3.addStretch()
        control_layout.addLayout(row3)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # 记录表格
        table_group = QGroupBox("解析记录")
        table_layout = QVBoxLayout()

        toolbar = QHBoxLayout()
        self.reload_btn = PushButton("刷新记录")
        self.reload_btn.setIcon(FluentIcon.SYNC)
        self.reload_btn.clicked.connect(self._reload_records)
        toolbar.addWidget(self.reload_btn)

        self.rename_btn = PushButton("手动补充姓名")
        self.rename_btn.clicked.connect(self.rename_selected)
        toolbar.addWidget(self.rename_btn)

        self.export_btn = PrimaryPushButton("导出 Excel")
        self.export_btn.setIcon(FluentIcon.DOCUMENT)
        self.export_btn.clicked.connect(self.export_excel)
        toolbar.addWidget(self.export_btn)

        self.open_dir_btn = PushButton("打开保存目录")
        self.open_dir_btn.clicked.connect(self.open_save_dir)
        toolbar.addWidget(self.open_dir_btn)

        toolbar.addStretch()
        self.record_count_label = QLabel("记录: 0")
        toolbar.addWidget(self.record_count_label)
        table_layout.addLayout(toolbar)

        self.records_table = TableWidget()
        self.records_table.setColumnCount(8)
        self.records_table.setHorizontalHeaderLabels(
            ["时间", "群", "文件名", "姓名", "状态", "发送人", "备注", "文件路径"]
        )
        self.records_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.records_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.records_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.records_table.setAlternatingRowColors(True)
        table_layout.addWidget(self.records_table)

        table_group.setLayout(table_layout)
        layout.addWidget(table_group, 1)

        # 扫描日志
        log_group = QGroupBox("扫描日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)

    # ---------------- 检测/目录 ----------------

    def _get_manager(self):
        """惰性创建微信目录管理器（GUI 线程短操作）"""
        if self.manager is None:
            from wechat.wechat_manager import WeChatManager
            self.manager = WeChatManager()
        return self.manager

    def connect_wechat(self):
        """检测微信安装位置与聊天文件目录"""
        mgr = self._get_manager()
        self.log("正在检测微信安装位置与聊天文件目录...")
        if mgr.connect():
            self.conn_badge.setText("已检测")
            self.conn_badge.setLevel(InfoLevel.SUCCESS)
            self.dir_label.setText(mgr.chatfile_folder)
            self.log(f"微信安装位置: {mgr.wechat_exe}")
            self.log(f"聊天文件目录: {mgr.chatfile_folder}")
            self._refresh_session_combo()
        else:
            self.conn_badge.setText("检测失败")
            self.conn_badge.setLevel(InfoLevel.ERROR)
            self.log(f"微信目录检测失败: {mgr.last_error or '未知错误'}")
            if 'pywechat' in (mgr.last_error or '') or 'pyweixin' in (mgr.last_error or ''):
                QMessageBox.warning(
                    self, "缺少 pywechat127 模块",
                    "未检测到 pywechat127/pyweixin 模块。\n\n"
                    "如果使用的是打包后的 exe，请确认已按最新 spec 重新打包"
                    "（pywechat127 会随 exe 一起分发，无需用户安装）。\n\n"
                    "如果是源码运行，请先安装：\n"
                    "  pip install pywechat127"
                )

    def pick_chatfile_dir(self):
        """手动选择微信聊天文件目录（自动检测失败时使用）"""
        from PyQt5.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(
            self, "选择微信聊天文件目录（xwechat_files/<wxid>/msg/file）"
        )
        if not folder:
            return
        from wechat.wechat_config import load_wechat_config, save_wechat_config
        config = load_wechat_config()
        config["chatfile_dir"] = folder
        save_wechat_config(config)
        self.log(f"已保存聊天文件目录: {folder}")
        # 立即用新目录检测
        mgr = self._get_manager()
        if mgr.connect():
            self.conn_badge.setText("已检测")
            self.conn_badge.setLevel(InfoLevel.SUCCESS)
            self.dir_label.setText(mgr.chatfile_folder)
            self._refresh_session_combo()
            self.log("目录检测成功")
        else:
            self.log(f"目录检测失败: {mgr.last_error}")

    def _refresh_session_combo(self):
        """获取聊天文件目录月份并填充下拉框（兼容旧界面）"""
        mgr = self._get_manager()
        if not mgr.connected:
            return
        sessions = mgr.get_sessions()
        if not sessions:
            self.log("聊天文件目录中暂无月份子目录")
            return
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem("全部")
        for name in sessions:
            self.session_combo.addItem(name)
        self.session_combo.blockSignals(False)
        self.log(f"发现 {len(sessions)} 个月份目录")

    # ---------------- 扫描 ----------------

    def start_listen(self):
        """开始扫描解析聊天文件目录"""
        if self.monitor and self.monitor.isRunning():
            self.log("已在扫描中，请先停止")
            return
        if not (self._get_manager().connected):
            self.log("请先点击“检测微信目录”")
            QMessageBox.information(self, "提示", "请先点击“检测微信目录”")
            return

        from wechat.wechat_monitor import WeChatMonitorThread
        group_name = self.session_combo.currentText().strip() or '全部'
        self.monitor = WeChatMonitorThread(self.db, group_name, parent=self)
        self.monitor.new_record.connect(self._on_new_record)
        self.monitor.log_message.connect(self.log)
        self.monitor.status_changed.connect(self._on_listen_status)
        self.monitor.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.listen_badge.setText("扫描中")
        self.listen_badge.setLevel(InfoLevel.INFOAMTION)
        self.log(f"正在扫描目录: {self._get_manager().chatfile_folder}")

    def stop_listen(self):
        """停止扫描"""
        if self.monitor and self.monitor.isRunning():
            self.monitor.stop_monitor()
            self.monitor.wait(5000)
        self.monitor = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.listen_badge.setText("未扫描")
        self.listen_badge.setLevel(InfoLevel.INFOAMTION)
        self.log("扫描已停止")

    def _on_listen_status(self, state):
        if state == 'scanning':
            self.listen_badge.setText("扫描中")
            self.listen_badge.setLevel(InfoLevel.SUCCESS)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif state == 'error':
            self.listen_badge.setText("扫描异常")
            self.listen_badge.setLevel(InfoLevel.ERROR)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        elif state == 'stopped':
            if self.monitor and self.monitor.isRunning():
                return
            self.listen_badge.setText("未扫描")
            self.listen_badge.setLevel(InfoLevel.INFOAMTION)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _on_new_record(self, record):
        """扫描线程上报新记录 -> 表格顶部插入一行"""
        row = 0
        self.records_table.insertRow(row)
        values = [
            record.get('created_at', '') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            record.get('group_name', ''),
            record.get('file_name', ''),
            record.get('candidate_name', ''),
            STATUS_LABELS.get(record.get('status', ''), record.get('status', '')),
            record.get('sender', ''),
            record.get('error_message', ''),
            record.get('file_path', ''),
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if col == 0:
                item.setData(Qt.UserRole, record.get('id'))
            self.records_table.setItem(row, col, item)
        self._update_count()

    def _reload_records(self):
        """从数据库加载最近的解析记录"""
        try:
            records = self.db.get_wechat_records(limit=200)
        except Exception as e:
            self.log(f"加载记录失败: {e}")
            return
        self.records_table.setRowCount(0)
        for record in records:
            row = self.records_table.rowCount()
            self.records_table.insertRow(row)
            values = [
                record.get('created_at', '') or '',
                record.get('group_name', '') or '',
                record.get('file_name', '') or '',
                record.get('candidate_name', '') or '',
                STATUS_LABELS.get(record.get('status', ''), record.get('status', '') or ''),
                record.get('sender', '') or '',
                record.get('error_message', '') or '',
                record.get('file_path', '') or '',
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, record.get('id'))
                self.records_table.setItem(row, col, item)
        self._update_count()

    def _update_count(self):
        self.record_count_label.setText(f"记录: {self.records_table.rowCount()}")

    # ---------------- 手动改名 / 导出 ----------------

    def rename_selected(self):
        """对解析失败的记录手动补充姓名"""
        row = self.records_table.currentRow()
        if row < 0:
            self.log("请先在表格中选择一行记录")
            return
        id_item = self.records_table.item(row, 0)
        record_id = id_item.data(Qt.UserRole) if id_item else None
        if not record_id:
            self.log("无法获取选中记录")
            return
        file_name = self.records_table.item(row, 2).text() if self.records_table.item(row, 2) else ''
        name, ok = QInputDialog.getText(
            self, "补充姓名",
            f"文件：{file_name}\n请输入候选人姓名：",
        )
        if not ok or not name.strip():
            return
        try:
            self.db.update_wechat_record_name(int(record_id), name.strip())
            self.log(f"已更新记录姓名: {file_name} -> {name.strip()}")
            self._reload_records()
        except Exception as e:
            self.log(f"更新姓名失败: {e}")

    def export_excel(self):
        """导出解析记录到 Excel（独立导出，不影响前程无忧的结果文件）"""
        try:
            import pandas as pd
            from wechat.wechat_config import load_wechat_config
            from wechat.wechat_parser import parse_candidate_name
            records = self.db.get_wechat_records(limit=10000)
            if not records:
                self.log("当前没有可导出的记录")
                QMessageBox.information(self, "提示", "当前没有可导出的记录")
                return
            config = load_wechat_config()
            prefixes = config.get("company_prefixes") or []
            rows = []
            for rec in records:
                file_name = rec.get('file_name', '') or ''
                created = rec.get('created_at', '') or ''
                # 推荐简历日期：只取年月日
                date_part = str(created)[:10] if created else ''
                # 推荐人姓名：优先用解析结果，缺失时尝试从文件名再解析
                candidate = rec.get('candidate_name', '') or ''
                if not candidate:
                    candidate = parse_candidate_name(file_name, prefixes) or ''
                # 推荐岗位：去掉公司前缀后取第一段（如 广州海颐-前端工程师-张三 -> 前端工程师）
                position = ''
                stem = Path(file_name).stem
                for p in prefixes or []:
                    if stem.startswith(p):
                        stem = stem[len(p):].lstrip('-').lstrip('_').strip()
                        break
                parts = re.split(r'[-_－—]', stem)
                if parts and parts[0].strip():
                    position = parts[0].strip()
                rows.append({
                    "供应商": '',
                    "项目/部门": "综合业务",
                    "推荐简历日期": date_part,
                    "推荐人姓名": candidate,
                    "查重列": 0,
                    "推荐岗位": position,
                    "文件名": file_name,
                    "状态": STATUS_LABELS.get(rec.get('status', ''), rec.get('status', '') or ''),
                    "备注": rec.get('error_message', '') or '',
                    "文件路径": rec.get('file_path', '') or '',
                })
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_path = _BASE_DIR / "output" / f"wechat_resumes_{timestamp}.xlsx"
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_excel(excel_path, index=False, sheet_name="微信简历")
            self.log(f"已导出 {len(rows)} 条记录: {excel_path}")
            QMessageBox.information(self, "导出成功", f"已导出 {len(rows)} 条记录：\n{excel_path}")
        except Exception as e:
            self.log(f"导出失败: {e}")
            QMessageBox.warning(self, "导出失败", str(e))

    def open_save_dir(self):
        """打开文件保存目录"""
        from wechat.wechat_config import resolve_save_dir
        try:
            path = resolve_save_dir()
            import os
            os.startfile(str(path))  # noqa: S606 - 用户主动点击打开本地目录
        except Exception as e:
            self.log(f"打开目录失败: {e}")

    # ---------------- 日志 / 退出 ----------------

    def log(self, message):
        from datetime import datetime as _dt
        timestamp = _dt.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def shutdown(self):
        """退出前停止扫描线程"""
        if self.monitor and self.monitor.isRunning():
            self.monitor.stop_monitor()
            self.monitor.wait(5000)
        self.monitor = None
