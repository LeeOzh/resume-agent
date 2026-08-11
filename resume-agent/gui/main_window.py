# -*- coding: utf-8 -*-
"""
主窗口模块 - AI 简历批量初筛与下载助手
"""
import sys
import os
import json
import multiprocessing
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
    QToolBar, QStatusBar, QMenuBar, QHeaderView, QCheckBox,
    QPushButton, QLabel, QGroupBox, QGridLayout,
    QLineEdit, QDialog, QMessageBox, QProgressBar, QApplication,
    QFileDialog, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QAction, QFont, QColor

# 获取基础目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent

sys.path.insert(0, str(_BASE_DIR))
from config import load_ai_config, save_ai_config
from db import Database


def refresh_worker_target(queue, switch_job):
    """刷新候选人子进程目标函数"""
    try:
        from browser_worker import run
        result = run(switch_job)
        queue.put(result)
    except Exception as e:
        queue.put({'success': False, 'error': str(e)})


def download_worker_target(queue, candidates, download_dir, job_name, 
                           ai_config, download_all_pages, stop_event, task_id=None):
    """下载子进程目标函数"""
    try:
        from download_worker import run
        result = run(candidates, download_dir, job_name, ai_config, 
                    download_all_pages, stop_event, task_id)
        queue.put(result)
    except Exception as e:
        queue.put({'success': False, 'error': str(e)})


class DBWorkerThread(QThread):
    """数据库后台操作线程"""
    finished = pyqtSignal()
    
    def __init__(self, db, func, *args, **kwargs):
        super().__init__()
        self.db = db
        self.func = func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        try:
            self.func(*self.args, **self.kwargs)
        except Exception as e:
            print(f"DB操作失败: {e}")
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    """主窗口类"""

    def __init__(self):
        super().__init__()
        self.candidates = []
        self.worker_process = None
        self.allowed_schools = set()
        self.school_filter_enabled = False
        self.school_list_path = ""
        self.positions = []
        self.current_job = ""
        self.total_pages = 1
        
        # 数据库
        self.db = Database()
        self.current_task_id = None
        
        # 跨进程中断信号
        self.stop_event = multiprocessing.Event()

        self.setWindowTitle("AI 简历批量初筛与下载助手")
        self.setMinimumSize(1200, 800)

        self.load_stylesheet()
        self.setup_ui()
        self.setup_menu()
        self.setup_toolbar()
        self.setup_statusbar()

        # 定时器检查子进程状态
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_worker_status)
        self.result_queue = None
        self.current_task = None
        self.worker_start_time = None

        # 尝试加载上次的学校名单
        self.load_last_school_list()

        # 启动后自动尝试连接浏览器（带端口检测，避免启动崩溃）
        QTimer.singleShot(500, self.auto_refresh)

    def load_stylesheet(self):
        try:
            style_path = _BASE_DIR / "gui" / "resources" / "styles" / "default.qss"
            if style_path.exists():
                with open(style_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
        except Exception:
            pass

    def load_last_school_list(self):
        """加载上次使用的学校名单路径"""
        path = ''
        # 1. 统一配置文件 school_filter_config.json
        try:
            from config import load_school_filter_config
            path = load_school_filter_config().get('school_list_path', '')
        except Exception:
            pass
        # 2. 兼容旧的 school_list_path.txt
        if not path or not Path(path).exists():
            legacy_path = _BASE_DIR / "school_list_path.txt"
            try:
                if legacy_path.exists():
                    p = legacy_path.read_text(encoding="utf-8").strip()
                    if p and Path(p).exists():
                        path = p
            except Exception:
                pass
        # 3. 回退到 config.py 的默认路径
        if not path or not Path(path).exists():
            try:
                from config import SCHOOL_LIST_PATH
                if SCHOOL_LIST_PATH.exists():
                    path = str(SCHOOL_LIST_PATH)
            except Exception:
                pass

        if path:
            self.school_list_path = path
            self.load_school_list(path)

    def save_school_list_path(self, path):
        """保存学校名单路径"""
        try:
            from config import save_school_filter_config
            save_school_filter_config({'school_list_path': path})
        except Exception:
            pass
        # 兼容旧文件
        try:
            legacy_path = _BASE_DIR / "school_list_path.txt"
            with open(legacy_path, "w", encoding="utf-8") as f:
                f.write(path)
        except Exception:
            pass

    def load_school_list(self, file_path):
        """加载学校名单"""
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            self.allowed_schools = set()
            for _, row in df.iterrows():
                name = str(row.get('学校名称', '')).strip()
                if name and name != 'nan':
                    self.allowed_schools.add(name)
            self.school_count_label.setText(f"已加载 {len(self.allowed_schools)} 所可录用学校")
            self.school_count_label.setStyleSheet("color: green;")
            return True
        except Exception as e:
            self.school_count_label.setText(f"加载失败: {e}")
            self.school_count_label.setStyleSheet("color: red;")
            return False

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：候选人列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # 表格工具栏
        table_toolbar = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_candidates)
        self.deselect_all_btn = QPushButton("取消全选")
        self.deselect_all_btn.clicked.connect(self.deselect_all_candidates)

        table_toolbar.addWidget(self.select_all_btn)
        table_toolbar.addWidget(self.deselect_all_btn)
        table_toolbar.addStretch()
        left_layout.addLayout(table_toolbar)

        self.candidate_table = QTableWidget()
        self.candidate_table.setColumnCount(5)
        self.candidate_table.setHorizontalHeaderLabels(["选择", "姓名", "学校", "专业", "学历"])
        self.candidate_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.candidate_table.setAlternatingRowColors(True)
        left_layout.addWidget(self.candidate_table)

        splitter.addWidget(left_widget)

        # 右侧：控制面板和日志
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 职位选择组
        job_group = QGroupBox("职位选择")
        job_layout = QHBoxLayout()

        job_layout.addWidget(QLabel("当前职位:"))
        self.job_combo = QComboBox()
        self.job_combo.setMinimumWidth(200)
        self.job_combo.currentTextChanged.connect(self.on_job_changed)
        job_layout.addWidget(self.job_combo)

        job_layout.addStretch()
        job_group.setLayout(job_layout)
        right_layout.addWidget(job_group)

        # 学校筛选组
        school_group = QGroupBox("学校名单筛选")
        school_layout = QVBoxLayout()

        school_btn_layout = QHBoxLayout()
        self.load_school_btn = QPushButton("载入学校名单")
        self.load_school_btn.clicked.connect(self.browse_school_list)
        school_btn_layout.addWidget(self.load_school_btn)

        self.school_filter_check = QCheckBox("启用筛选（只显示名单内学校）")
        self.school_filter_check.setChecked(False)
        self.school_filter_check.stateChanged.connect(self.toggle_school_filter)
        school_btn_layout.addWidget(self.school_filter_check)
        school_btn_layout.addStretch()
        school_layout.addLayout(school_btn_layout)

        self.school_count_label = QLabel("未载入学校名单")
        self.school_count_label.setStyleSheet("color: gray;")
        school_layout.addWidget(self.school_count_label)

        school_group.setLayout(school_layout)
        right_layout.addWidget(school_group)

        # 下载控制组
        control_group = QGroupBox("下载控制")
        control_layout = QGridLayout()

        control_layout.addWidget(QLabel("保存目录:"), 0, 0)
        self.download_dir_edit = QLineEdit()
        self.download_dir_edit.setText(str(_BASE_DIR / "output" / "resumes"))
        control_layout.addWidget(self.download_dir_edit, 0, 1)

        control_layout.addWidget(QLabel("页码:"), 1, 0)
        self.page_label = QLabel("第 1 页 / 共 1 页")
        control_layout.addWidget(self.page_label, 1, 1)

        control_layout.addWidget(QLabel("AI筛选:"), 2, 0)
        self.ai_enabled_label = QLabel("未配置")
        control_layout.addWidget(self.ai_enabled_label, 2, 1)

        # 下载按钮布局
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始下载")
        self.start_btn.clicked.connect(self.start_download)
        self.start_btn.setEnabled(False)

        self.stop_btn = QPushButton("中断下载")
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)

        self.download_all_check = QCheckBox("下载所有页")
        self.download_all_check.setChecked(False)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.download_all_check)
        btn_layout.addStretch()

        control_layout.addLayout(btn_layout, 3, 0, 1, 2)

        control_group.setLayout(control_layout)
        right_layout.addWidget(control_group)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        # 操作日志
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)

        log_btn_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_btn_layout.addWidget(self.clear_log_btn)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)

        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([700, 500])
        main_layout.addWidget(splitter)

    def setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        action_menu = menubar.addMenu("操作")
        refresh_action = QAction("刷新候选人", self)
        refresh_action.triggered.connect(self.refresh_candidates)
        action_menu.addAction(refresh_action)

        settings_menu = menubar.addMenu("设置")
        ai_config_action = QAction("AI配置", self)
        ai_config_action.triggered.connect(self.show_ai_config)
        settings_menu.addAction(ai_config_action)

        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_toolbar(self):
        toolbar = QToolBar("工具栏")
        self.addToolBar(toolbar)

        self.toolbar_refresh_btn = QPushButton("刷新列表")
        self.toolbar_refresh_btn.clicked.connect(self.refresh_candidates)
        toolbar.addWidget(self.toolbar_refresh_btn)

    def setup_statusbar(self):
        self.statusBar().showMessage("就绪")

        self.candidate_count_label = QLabel("候选人: 0")
        self.download_count_label = QLabel("已下载: 0")
        self.ai_status_label = QLabel("AI: 未配置")

        self.statusBar().addPermanentWidget(self.candidate_count_label)
        self.statusBar().addPermanentWidget(self.download_count_label)
        self.statusBar().addPermanentWidget(self.ai_status_label)

    def browse_school_list(self):
        """浏览选择学校名单文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择学校名单文件",
            str(_BASE_DIR),
            "Excel文件 (*.xlsx *.xls);;所有文件 (*.*)"
        )

        if file_path:
            self.school_list_path = file_path
            if self.load_school_list(file_path):
                self.save_school_list_path(file_path)
                self.log(f"已载入学校名单: {Path(file_path).name}")
                if self.school_filter_enabled and self.candidates:
                    self.update_candidate_table()

    def toggle_school_filter(self, state):
        """切换学校筛选状态"""
        self.school_filter_enabled = state == 2
        if self.candidates:
            self.update_candidate_table()

    def on_job_changed(self, job_name):
        """职位切换"""
        if not job_name or job_name == self.current_job:
            return

        if not self.positions:
            return

        current_active = ''
        for pos in self.positions:
            if pos.get('active'):
                current_active = pos.get('name', '')
                break

        if job_name == current_active:
            return

        self.log(f"切换到职位: {job_name}")
        self.current_job = job_name
        self.refresh_candidates(switch_job=job_name)

    def auto_refresh(self):
        """初始化自动获取"""
        self.log("正在检查 Chrome 调试模式...")
        if not self._ensure_chrome_debug():
            return
        self.log("正在自动连接浏览器并获取候选人列表...")
        try:
            self.refresh_candidates()
        except Exception as e:
            self.log(f"自动刷新失败: {e}")

    def _is_chrome_port_open(self):
        """检测 Chrome 调试端口是否已开放"""
        try:
            import socket
            from config import CHROME_DEBUG_PORT
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            port_open = sock.connect_ex(('127.0.0.1', CHROME_DEBUG_PORT)) == 0
            sock.close()
            return port_open
        except Exception:
            return False

    def _ensure_chrome_debug(self):
        """确保 Chrome 调试模式已启动，未启动则自动启动"""
        if self._is_chrome_port_open():
            return True
        self.log("未检测到 Chrome 调试模式，正在自动启动 Chrome...")
        try:
            from browser.chrome import ensure_chrome_debug
            from config import CHROME_DEBUG_PORT
            if ensure_chrome_debug(port=CHROME_DEBUG_PORT, wait_seconds=30):
                self.log("Chrome 调试模式已启动")
                return True
            self.log("Chrome 调试模式启动失败或超时，请检查 Chrome 是否已安装")
        except Exception as e:
            self.log(f"自动启动 Chrome 异常: {e}")
        return False

    def refresh_candidates(self, switch_job=''):
        """刷新候选人列表"""
        if self.worker_process and self.worker_process.is_alive():
            self.log("正在获取中，请等待...")
            return

        # 确保 Chrome 调试模式已启动（未启动时自动启动）
        if not self._ensure_chrome_debug():
            return

        if switch_job:
            self.log(f"正在切换职位并获取候选人列表...")
        else:
            self.log("正在连接浏览器并获取候选人列表...")

        self.set_buttons_enabled(False)
        self.current_task = 'refresh'
        import time
        self.worker_start_time = time.time()

        self.result_queue = multiprocessing.Queue()

        self.worker_process = multiprocessing.Process(
            target=refresh_worker_target,
            args=(self.result_queue, switch_job),
            daemon=True
        )
        self.worker_process.start()

        self.check_timer.start(500)

    def start_download(self):
        """开始下载"""
        selected = self.get_selected_candidates()
        if not selected:
            self.log("请先选择要下载的候选人")
            return

        if self.worker_process and self.worker_process.is_alive():
            self.log("有任务正在执行，请等待...")
            return

        download_dir = self.download_dir_edit.text()
        job_name = self.current_job
        ai_config = load_ai_config()
        download_all = self.download_all_check.isChecked()

        if ai_config.get("enabled") and ai_config.get("api_key"):
            # 按当前职位查找匹配描述（job_descriptions -> match_description）
            job_descs = ai_config.get("job_descriptions", {})
            match_desc = job_descs.get(job_name, '')
            ai_config["match_description"] = match_desc
            if not match_desc:
                self.log("警告: 当前职位未配置匹配描述，AI 将按空描述评估")
        else:
            ai_config = None

        # 重置中断信号
        self.stop_event.clear()

        # 同步创建数据库任务，确保 task_id 在下载子进程启动前可用
        task_id = self._create_task_and_candidates(
            job_name, ai_config, download_dir, download_all, len(selected)
        )

        if download_all:
            self.log(f"开始下载所有页简历...")
        else:
            self.log(f"开始下载 {len(selected)} 个候选人简历...")

        # 显示中断按钮
        self.start_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)

        self.set_buttons_enabled(False)
        self.current_task = 'download'
        import time
        self.worker_start_time = time.time()

        self.result_queue = multiprocessing.Queue()

        # 传递 stop_event 与 task_id 给子进程
        self.worker_process = multiprocessing.Process(
            target=download_worker_target,
            args=(self.result_queue, selected, download_dir, job_name, 
                  ai_config, download_all, self.stop_event, task_id),
            daemon=True
        )
        self.worker_process.start()

        self.check_timer.start(500)
    
    def _create_task_and_candidates(self, job_name, ai_config, download_dir, download_all, total):
        """同步创建数据库任务并写入候选人记录，返回 task_id"""
        try:
            task = self.db.create_task(
                job_name=job_name,
                ai_config=ai_config if ai_config else {},
                download_dir=download_dir,
                download_all_pages=download_all,
                total_candidates=total
            )
            self.current_task_id = task.id
            self.db.update_task_status(task.id, 'running')
            # 单页模式预写入选中候选人；分页模式由下载进程按页补充
            if not download_all:
                candidates = self.get_selected_candidates()
                self.db.add_candidates_batch(task.id, [dict(c, page=1) for c in candidates])
            self.db.add_task_log(task.id, 'info', f'开始下载 {total} 个候选人')
            return task.id
        except Exception as e:
            self.log(f"创建任务失败: {e}")
            print(f"创建任务失败: {e}")
            return None

    def stop_download(self):
        """中断下载"""
        self.stop_event.set()
        self.log("正在中断下载，请等待当前候选人处理完成...")
        self.stop_btn.setEnabled(False)

    def set_buttons_enabled(self, enabled):
        """设置按钮启用状态"""
        self.select_all_btn.setEnabled(enabled)
        self.deselect_all_btn.setEnabled(enabled)
        self.toolbar_refresh_btn.setEnabled(True)
        self.start_btn.setEnabled(enabled and bool(self.candidates))
        self.job_combo.setEnabled(enabled)
        self.download_all_check.setEnabled(enabled)

    def check_worker_status(self):
        """检查子进程状态"""
        try:
            if not self.worker_process:
                self.check_timer.stop()
                self.set_buttons_enabled(True)
                self.start_btn.setVisible(True)
                self.stop_btn.setVisible(False)
                return

            if self.worker_process.is_alive():
                # 刷新任务看门狗：超过90秒无结果则终止，避免界面卡死
                import time
                if (self.current_task == 'refresh' and self.worker_start_time
                        and time.time() - self.worker_start_time > 90):
                    self.log("刷新超时，已终止该次获取，请重试")
                    self.worker_process.terminate()
                    self.worker_process.join(timeout=3)
                    self.worker_process = None
                    self.current_task = None
                    self.worker_start_time = None
                    self.check_timer.stop()
                    self.set_buttons_enabled(True)
                    self.start_btn.setVisible(True)
                    self.stop_btn.setVisible(False)
                return

            self.check_timer.stop()
            self.set_buttons_enabled(True)
            self.start_btn.setVisible(True)
            self.stop_btn.setVisible(False)

            if self.result_queue and not self.result_queue.empty():
                result = self.result_queue.get()

                if self.current_task == 'refresh':
                    self._on_refresh_finished(result)
                elif self.current_task == 'download':
                    self._on_download_finished(result)

            else:
                self.log("任务失败：无结果")

            self.current_task = None
            self.worker_start_time = None
        except Exception as e:
            import traceback
            self.log(f"检查任务状态异常: {e}")
            traceback.print_exc()
            self.current_task = None
            self.worker_start_time = None
            self.check_timer.stop()
            self.set_buttons_enabled(True)
            self.start_btn.setVisible(True)
            self.stop_btn.setVisible(False)

    def _on_refresh_finished(self, result):
        """刷新完成回调"""
        try:
            if not result.get('success'):
                error = result.get('error', '未知错误')
                self.log(f"获取失败: {error}")
                return
            positions = result.get('positions', [])
            self.positions = positions
            active = result.get('active_position', '')
            self.current_job = active

            # 异步同步岗位到数据库
            self._async_sync_jobs(positions)

            self.job_combo.blockSignals(True)
            self.job_combo.clear()
            for pos in positions:
                name = pos.get('name', '')
                self.job_combo.addItem(name)

            if active:
                index = self.job_combo.findText(active)
                if index >= 0:
                    self.job_combo.setCurrentIndex(index)
            self.job_combo.blockSignals(False)

            if positions:
                self.log(f"检测到 {len(positions)} 个职位，当前: {active}")
            else:
                self.log("未检测到职位信息，请确保已在候选人管理页面")

            # 更新页码和总页数
            current_page = result.get('current_page', 1)
            self.total_pages = result.get('total_pages', 1)
            self.page_label.setText(f"第 {current_page} 页 / 共 {self.total_pages} 页")

            candidates = result.get('candidates', [])
            self.candidates = candidates
            self.update_candidate_table()

            total = len(candidates)
            if self.school_filter_enabled:
                filtered = sum(1 for c in candidates if self.is_school_allowed(c.get('school', '')))
                self.log(f"获取到 {total} 个候选人，学校筛选后 {filtered} 个")
            else:
                self.log(f"获取到 {total} 个候选人")

            self.candidate_count_label.setText(f"候选人: {total}")

            # 启用开始下载按钮
            if candidates:
                self.start_btn.setEnabled(True)
                
            # 检查是否有未完成的任务
            QTimer.singleShot(500, self.check_unfinished_tasks)
        except Exception as e:
            import traceback
            self.log(f"处理刷新结果异常: {e}")
            traceback.print_exc()
    
    def _async_sync_jobs(self, positions):
        """异步同步岗位到数据库"""
        def do_sync():
            try:
                self.db.sync_jobs(positions)
            except Exception as e:
                print(f"同步岗位失败: {e}")
        
        thread = DBWorkerThread(self.db, do_sync)
        thread.start()
    
    def check_unfinished_tasks(self):
        """检查是否有未完成的任务"""
        try:
            unfinished = self.db.get_unfinished_tasks()
            if unfinished:
                task = unfinished[0]
                reply = QMessageBox.question(
                    self, "恢复任务",
                    f"发现未完成的任务：\n\n"
                    f"任务ID: #{task.id}\n"
                    f"岗位: {task.job_name}\n"
                    f"状态: {task.status}\n"
                    f"进度: {task.processed_count}/{task.total_candidates}\n\n"
                    f"是否恢复该任务？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.resume_task(task)
        except Exception as e:
            print(f"检查未完成任务失败: {e}")
    
    def resume_task(self, task):
        """恢复任务"""
        try:
            pending = self.db.get_pending_candidates(task.id)
            if not pending:
                self.log(f"任务 #{task.id} 没有待处理的候选人，标记为完成")
                self.db.update_task_status(task.id, 'completed')
                return

            # 标记任务为运行中
            self.db.update_task_status(task.id, 'running')
            self.current_task_id = task.id

            # 恢复下载配置
            self.job_combo.setCurrentText(task.job_name)
            download_dir = task.download_dir or str(_BASE_DIR / "output" / "resumes")
            self.download_dir_edit.setText(download_dir)

            # 从任务快照恢复 AI 配置
            ai_config = None
            if task.ai_enabled and task.ai_api_key:
                ai_config = {
                    "enabled": True,
                    "api_key": task.ai_api_key,
                    "match_description": task.ai_match_description,
                    "job_descriptions": {},
                }

            # 从数据库恢复待处理候选人（含学校/专业/学历信息）
            candidates = [
                {
                    "name": c.name,
                    "school": c.school,
                    "major": c.major,
                    "education": c.education,
                    "page": c.page_num,
                }
                for c in pending
            ]

            self.log(f"恢复任务 #{task.id}: {task.job_name}，待处理 {len(candidates)} 个候选人")
            self.log("提示: 请确保浏览器停留在原任务中断时的页面")

            # 重置中断信号
            self.stop_event.clear()

            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(True)
            self.stop_btn.setEnabled(True)

            self.set_buttons_enabled(False)
            self.current_task = 'download'
            import time
            self.worker_start_time = time.time()

            self.result_queue = multiprocessing.Queue()
            self.worker_process = multiprocessing.Process(
                target=download_worker_target,
                args=(self.result_queue, candidates, download_dir, task.job_name,
                      ai_config, False, self.stop_event, task.id),
                daemon=True
            )
            self.worker_process.start()
            self.check_timer.start(500)
        except Exception as e:
            import traceback
            self.log(f"恢复任务失败: {e}")
            traceback.print_exc()

    def _on_download_finished(self, result):
        """下载完成回调"""
        try:
            if not result.get('success'):
                error = result.get('error', '未知错误')
                self.log(f"下载失败: {error}")
                self._async_update_task_on_fail(error)
                return
            results = result.get('results', [])
            success_count = sum(1 for r in results if r.get('success'))
            fail_count = len(results) - success_count
            total_pages = result.get('total_pages', 1)

            self.log(f"下载完成: 成功 {success_count} 个，失败 {fail_count} 个，共 {total_pages} 页")

            # 异步更新数据库任务状态
            paused = self.stop_event.is_set()
            self._async_update_task_on_complete(
                results, success_count, fail_count, total_pages, paused=paused
            )

            # 导出结果
            if results:
                self.export_results(results)
        except Exception as e:
            import traceback
            self.log(f"处理下载结果异常: {e}")
            traceback.print_exc()
    
    def _async_update_task_on_complete(self, results, success_count, fail_count, total_pages, paused=False):
        """异步更新任务完成状态"""
        task_id = self.current_task_id
        
        def do_update():
            try:
                if not task_id:
                    return
                self.db.update_task_progress(
                    task_id,
                    processed_count=len(results),
                    success_count=success_count,
                    failed_count=fail_count,
                    total_pages=total_pages
                )
                status = 'paused' if paused else 'completed'
                self.db.update_task_status(task_id, status)
                self.db.add_task_log(task_id, 'info', 
                    f'任务{"已暂停" if paused else "完成"}: 成功 {success_count}, 失败 {fail_count}')
            except Exception as e:
                print(f"更新任务状态失败: {e}")
        
        self.current_task_id = None
        thread = DBWorkerThread(self.db, do_update)
        thread.start()
    
    def _async_update_task_on_fail(self, error):
        """异步更新任务失败状态"""
        task_id = self.current_task_id
        
        def do_update():
            try:
                if task_id:
                    self.db.update_task_status(task_id, 'failed')
                    self.db.add_task_log(task_id, 'error', f'任务失败: {error}')
            except Exception as e:
                print(f"更新任务状态失败: {e}")
        
        self.current_task_id = None
        thread = DBWorkerThread(self.db, do_update)
        thread.start()

    def export_results(self, results):
        """导出下载结果"""
        try:
            from datetime import datetime
            download_dir = Path(self.download_dir_edit.text())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_path = download_dir.parent / f"result_{timestamp}.xlsx"

            import pandas as pd
            rows = []
            for r in results:
                status = "成功" if r.get('success') else "失败"
                rows.append({
                    "职位": self.current_job,
                    "姓名": r.get('name', ''),
                    "页码": r.get('page', ''),
                    "下载状态": status,
                    "AI评估": "通过" if r.get('ai_pass') is True else ("不通过" if r.get('ai_pass') is False else "未评估"),
                    "文件路径": r.get('file_path', ''),
                    "错误/原因": r.get('error', ''),
                })

            df = pd.DataFrame(rows)
            df.to_excel(excel_path, index=False, sheet_name="下载结果")
            self.log(f"结果已导出: {excel_path}")
        except Exception as e:
            self.log(f"导出结果失败: {e}")

    def is_school_allowed(self, school):
        """检查学校是否在允许名单中"""
        if not school or not self.school_filter_enabled:
            return True

        if school in self.allowed_schools:
            return True

        for allowed in self.allowed_schools:
            if allowed in school or school in allowed:
                return True

        return False

    def update_candidate_table(self):
        """更新候选人表格"""
        display_candidates = []
        for c in self.candidates:
            if self.school_filter_enabled:
                if self.is_school_allowed(c.get('school', '')):
                    display_candidates.append(c)
            else:
                display_candidates.append(c)

        self.candidate_table.setRowCount(len(display_candidates))

        for i, candidate in enumerate(display_candidates):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self.candidate_table.setCellWidget(i, 0, checkbox)

            name = candidate.get('name', '')
            self.candidate_table.setItem(i, 1, QTableWidgetItem(name))

            school = candidate.get('school', '')
            school_item = QTableWidgetItem(school)
            if school and not self.is_school_allowed(school):
                school_item.setForeground(QColor(255, 0, 0))
            self.candidate_table.setItem(i, 2, school_item)

            major = candidate.get('major', '')
            self.candidate_table.setItem(i, 3, QTableWidgetItem(major))

            education = candidate.get('education', '')
            self.candidate_table.setItem(i, 4, QTableWidgetItem(education))

    def select_all_candidates(self):
        for i in range(self.candidate_table.rowCount()):
            checkbox = self.candidate_table.cellWidget(i, 0)
            if checkbox:
                checkbox.setChecked(True)

    def deselect_all_candidates(self):
        for i in range(self.candidate_table.rowCount()):
            checkbox = self.candidate_table.cellWidget(i, 0)
            if checkbox:
                checkbox.setChecked(False)

    def get_selected_candidates(self):
        """返回选中的候选人（完整信息 dict，供下载与数据库持久化使用）"""
        selected = []
        for i in range(self.candidate_table.rowCount()):
            checkbox = self.candidate_table.cellWidget(i, 0)
            if checkbox and checkbox.isChecked():
                name_item = self.candidate_table.item(i, 1)
                if not name_item:
                    continue
                name = name_item.text()
                # 从 self.candidates 找回完整信息（学校/专业/学历）
                found = None
                for c in self.candidates:
                    if c.get('name') == name:
                        found = c
                        break
                selected.append(dict(found) if found else {'name': name})
        return selected

    def show_ai_config(self):
        dialog = AIConfigDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = load_ai_config()
            if config.get("enabled") and config.get("api_key"):
                self.ai_status_label.setText("AI: 已启用")
                self.ai_status_label.setStyleSheet("color: green;")
            else:
                self.ai_status_label.setText("AI: 未启用")
                self.ai_status_label.setStyleSheet("color: gray;")

    def show_about(self):
        QMessageBox.about(self, "关于",
            "AI 简历批量初筛与下载助手\n\n"
            "基于Python + Playwright的浏览器自动化工具\n"
            "用于从前程无忧自动下载候选人简历\n"
            "支持AI简历筛选和学校名单过滤\n\n"
            "版本: 1.1.0")

    def log(self, message):
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def clear_log(self):
        self.log_text.clear()

    def closeEvent(self, event):
        if self.worker_process and self.worker_process.is_alive():
            reply = QMessageBox.question(
                self, "确认退出",
                "有任务正在运行，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            
            # 中断下载
            self.stop_event.set()
            self.worker_process.join(timeout=5)
            if self.worker_process.is_alive():
                self.worker_process.terminate()
        event.accept()


class AIConfigDialog(QDialog):
    """AI配置对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI简历筛选配置")
        self.setMinimumWidth(500)
        self.config = load_ai_config()
        self.setup_ui()
        self.load_config()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        api_group = QGroupBox("API配置")
        api_layout = QGridLayout()

        api_layout.addWidget(QLabel("API Key:"), 0, 0)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addWidget(self.api_key_edit, 0, 1)

        api_layout.addWidget(QLabel("启用AI筛选:"), 1, 0)
        self.enabled_check = QCheckBox()
        api_layout.addWidget(self.enabled_check, 1, 1)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        desc_group = QGroupBox("岗位匹配描述")
        desc_layout = QVBoxLayout()

        self.desc_table = QTableWidget()
        self.desc_table.setColumnCount(2)
        self.desc_table.setHorizontalHeaderLabels(["岗位名称", "匹配描述"])
        self.desc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        desc_layout.addWidget(self.desc_table)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加")
        self.add_btn.clicked.connect(self.add_description)
        self.remove_btn = QPushButton("删除")
        self.remove_btn.clicked.connect(self.remove_description)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        desc_layout.addLayout(btn_layout)

        desc_group.setLayout(desc_layout)
        layout.addWidget(desc_group)

        button_layout = QHBoxLayout()
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

    def load_config(self):
        self.api_key_edit.setText(self.config.get("api_key", ""))
        self.enabled_check.setChecked(self.config.get("enabled", False))
        job_descs = self.config.get("job_descriptions", {})
        self.desc_table.setRowCount(len(job_descs))
        for i, (name, desc) in enumerate(job_descs.items()):
            self.desc_table.setItem(i, 0, QTableWidgetItem(name))
            self.desc_table.setItem(i, 1, QTableWidgetItem(desc))

    def save_config(self):
        self.config["api_key"] = self.api_key_edit.text()
        self.config["enabled"] = self.enabled_check.isChecked()
        job_descs = {}
        for i in range(self.desc_table.rowCount()):
            name = self.desc_table.item(i, 0)
            desc = self.desc_table.item(i, 1)
            if name and desc:
                job_descs[name.text()] = desc.text()
        self.config["job_descriptions"] = job_descs
        save_ai_config(self.config)

    def add_description(self):
        row = self.desc_table.rowCount()
        self.desc_table.insertRow(row)
        self.desc_table.setItem(row, 0, QTableWidgetItem("新岗位"))
        self.desc_table.setItem(row, 1, QTableWidgetItem("请输入匹配描述"))

    def remove_description(self):
        current_row = self.desc_table.currentRow()
        if current_row >= 0:
            self.desc_table.removeRow(current_row)

    def accept(self):
        self.save_config()
        super().accept()
