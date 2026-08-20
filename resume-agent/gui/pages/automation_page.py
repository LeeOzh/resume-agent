# -*- coding: utf-8 -*-
from gui.qt_compat import AcceptRole, AlignCenter, DestructiveRole, HeaderStretch, Horizontal, MessageBoxNo, MessageBoxYes, RejectRole, ScrollBarAlwaysOff
"""
简历自动化页面

由原 MainWindow 的业务逻辑整体迁移而来（UI + 刷新/下载/恢复任务/浏览器状态等），
逻辑保持不变；窗口级内容（导航、状态栏、主题、AI 配置对话框）保留在 MainWindow。
"""
import sys
import os
import html
from pathlib import Path

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QHeaderView, QLabel, QGroupBox,
    QGridLayout, QLineEdit, QMessageBox, QProgressBar, QFileDialog,
    QFrame, QScrollArea
)
from gui.qt_compat import Qt, QTimer, pyqtSignal, QThread, QPropertyAnimation
from gui.qt_compat import QFont, QColor
from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, TableWidget,
    CheckBox as FluentCheckBox, LineEdit as FluentLineEdit, InfoLevel,
    FluentIcon,
)

from config import load_ai_config


# 获取基础目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent.parent


def download_worker_target(queue, candidates, download_dir, job_name,
                           ai_config, download_all_pages, stop_event, task_id=None,
                           pause_event=None, db_path=None):
    """下载子进程目标函数"""
    try:
        from download_worker import run
        result = run(candidates, download_dir, job_name, ai_config,
                     download_all_pages, stop_event, task_id, pause_event=pause_event,
                     db_path=db_path)
        queue.put(result)
    except Exception as e:
        queue.put({'success': False, 'error': str(e)})


class DBWorkerThread(QThread):
    """数据库后台操作线程

    注意：必须由外部持有引用直到 finished，否则 QThread 对象被垃圾回收时
    线程仍在运行，Qt 会直接 abort（表现为程序闪退）。
    """
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


class AutomationPage(QWidget):
    """简历自动化页面：候选人列表 + 职位选择 + 学校筛选 + 下载控制 + 操作日志"""

    def __init__(self, main):
        super().__init__(main)
        self.main = main

        # 窗口级共享引用（状态栏标签 / 刷新按钮 / 浏览器监控线程）
        self.db = main.db
        from gui.controllers import TaskController
        self.task_controller = TaskController()
        from gui.services import CandidateService
        self.candidate_service = CandidateService(self.db)
        from gui.services import JobService
        self.job_service = JobService(self.db)
        self.candidate_count_label = main.candidate_count_label
        self.download_count_label = main.download_count_label
        self.ai_status_label = main.ai_status_label
        self.browser_status_label = main.browser_status_label
        self.task_status_label = main.task_status_label
        self.toolbar_refresh_btn = main.toolbar_refresh_btn
        self.browser_monitor = main.browser_monitor
        from gui.controllers import BrowserController
        self.browser_controller = BrowserController(
            on_event=self._on_browser_event,
            monitor=self.browser_monitor,
        )
        from gui.controllers import DownloadController
        self.download_controller = DownloadController(monitor=self.browser_monitor)

        # 业务状态（原 MainWindow 全部搬入，逻辑不变）
        self.candidates = []
        self.school_filter_enabled = False
        self.school_list_path = ""
        self.positions = []
        self.current_job = ""
        self.total_pages = 1
        self.current_page_url = ""          # 当前候选人列表URL（存入任务）
        self.page_type = ''                 # 当前页面类型（经 BrowserController）
        self.login_status = ''              # 当前登录状态
        self._db_threads = []               # 持有 DB 后台线程引用，防止 QThread 被 GC 导致闪退
        self.current_task_id = None
        self.last_task_id = None
        self.current_task_obj = None
        self.current_task = None

        # 浏览器管理（BrowserController 持有页面侧 BrowserManager；监控与重连由后台线程负责）
        self.browser_state = 'DISCONNECTED'

        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_worker_status)
        self.worker_start_time = None
        self._progress_anim = None
        self._unfinished_checked = False

        self.setup_ui()
        self.refresh_ai_status()

        # 尝试加载上次的学校名单
        self.load_last_school_list()

    # ---------------- 界面 ----------------

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(12)

        splitter = QSplitter(Horizontal)
        splitter.setHandleWidth(6)
        layout.addWidget(splitter, 1)

        # 左侧：候选人列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # 表格工具栏
        table_toolbar = QHBoxLayout()
        self.select_all_btn = PushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_candidates)
        self.deselect_all_btn = PushButton("取消全选")
        self.deselect_all_btn.clicked.connect(self.deselect_all_candidates)

        table_toolbar.addWidget(self.select_all_btn)
        table_toolbar.addWidget(self.deselect_all_btn)
        table_toolbar.addStretch()
        left_layout.addLayout(table_toolbar)

        self.candidate_table = TableWidget()
        self.candidate_table.setColumnCount(6)
        self.candidate_table.setHorizontalHeaderLabels(["选择", "姓名", "学校", "专业", "学历", "处理记录"])
        self.candidate_table.horizontalHeader().setSectionResizeMode(1, HeaderStretch)
        self.candidate_table.horizontalHeader().setSectionResizeMode(2, HeaderStretch)
        self.candidate_table.horizontalHeader().setSectionResizeMode(5, HeaderStretch)
        self.candidate_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.candidate_table.setAlternatingRowColors(True)
        left_layout.addWidget(self.candidate_table)

        splitter.addWidget(left_widget)

        # 右侧：控制面板和日志
        right_widget = QWidget()
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        right_inner = QWidget()
        right_layout = QVBoxLayout(right_inner)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_scroll.setWidget(right_inner)
        right_container = QVBoxLayout(right_widget)
        right_container.setContentsMargins(0, 0, 0, 0)
        right_container.addWidget(right_scroll)

        # 职位选择组
        job_group = QGroupBox("职位选择")
        job_layout = QHBoxLayout()

        job_layout.addWidget(QLabel("当前职位:"))
        self.job_combo = ComboBox()
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
        self.load_school_btn = PushButton("载入学校名单")
        self.load_school_btn.clicked.connect(self.browse_school_list)
        school_btn_layout.addWidget(self.load_school_btn)

        self.school_filter_check = FluentCheckBox("启用筛选（只显示名单内学校）")
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
        self.download_dir_edit = FluentLineEdit()
        self.download_dir_edit.setText(str(_BASE_DIR / "output" / "resumes"))
        control_layout.addWidget(self.download_dir_edit, 0, 1)

        control_layout.addWidget(QLabel("页码:"), 1, 0)
        self.page_label = QLabel("第 1 页 / 共 1 页")
        control_layout.addWidget(self.page_label, 1, 1)

        control_layout.addWidget(QLabel("AI筛选:"), 2, 0)
        self.ai_enabled_label = QLabel("未配置")
        control_layout.addWidget(self.ai_enabled_label, 2, 1)

        control_layout.addWidget(QLabel("匹配描述:"), 3, 0)
        self.match_desc_combo = ComboBox()
        self.match_desc_combo.setToolTip("选择本次下载使用的岗位匹配描述（默认自动匹配当前岗位）")
        control_layout.addWidget(self.match_desc_combo, 3, 1)

        # 下载按钮布局
        btn_layout = QHBoxLayout()
        self.start_btn = PrimaryPushButton("开始下载")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.start_btn.clicked.connect(self.start_download)
        self.start_btn.setEnabled(False)

        self.stop_btn = PushButton("中断下载")
        self.stop_btn.setIcon(FluentIcon.CANCEL)
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)

        self.pause_btn = PushButton("暂停下载")
        self.pause_btn.setIcon(FluentIcon.PAUSE)
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setVisible(False)

        self.resume_btn = PushButton("继续任务")
        self.resume_btn.setIcon(FluentIcon.PLAY)
        self.resume_btn.clicked.connect(self.on_resume_clicked)
        self.resume_btn.setEnabled(False)
        self.resume_btn.setVisible(False)

        self.download_all_check = FluentCheckBox("下载所有页")
        self.download_all_check.setChecked(False)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.resume_btn)
        btn_layout.addWidget(self.download_all_check)
        btn_layout.addStretch()

        control_layout.addLayout(btn_layout, 4, 0, 1, 2)

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
        self.clear_log_btn = PushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_btn_layout.addWidget(self.clear_log_btn)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)

        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group, 1)

        splitter.addWidget(right_widget)
        splitter.setSizes([700, 500])

    # ---------------- 启动/退出 ----------------

    def start_auto(self):
        """启动后自动检查 Chrome / 未完成任务（原 MainWindow 启动逻辑）"""
        if os.environ.get("RA_NO_AUTO_REFRESH") != "1":
            QTimer.singleShot(500, self.auto_refresh)
            self._unfinished_checked = False
            QTimer.singleShot(3000, self._startup_check_unfinished)
        else:
            self._unfinished_checked = True

    def shutdown(self) -> bool:
        """退出前清理；返回 False 表示用户取消退出"""
        if self.download_controller.is_worker_alive():
            reply = QMessageBox.question(
                self, "确认退出",
                "有任务正在运行，确定要退出吗？",
                MessageBoxYes | MessageBoxNo
            )
            if reply == MessageBoxNo:
                return False
            # 中断下载
            self.download_controller.stop()
            self.download_controller.shutdown_worker()

        # 结束刷新子进程（BrowserController 管理）
        if self.browser_controller.is_worker_alive():
            self.browser_controller.kill_worker()

        # 等待数据库后台线程结束（防止退出时 QThread 仍在运行导致 abort）
        for thread in list(self._db_threads):
            try:
                thread.wait(3000)
            except Exception:
                pass
        # 等待任务控制器线程结束（任务完成/失败异步更新）
        self.task_controller.shutdown(timeout_ms=3000)
        return True

    # ---------------- 学校名单 ----------------

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
        ok = self.candidate_service.load_school_list(file_path)
        if ok:
            self.school_count_label.setText(
                f"已加载 {self.candidate_service.school_count()} 所可录用学校"
            )
            self.school_count_label.setStyleSheet("color: green;")
        else:
            err = getattr(self.candidate_service, 'last_error', '') or ''
            self.school_count_label.setText(f"加载失败: {err}")
            self.school_count_label.setStyleSheet("color: red;")
        return ok

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
        self.candidate_service.set_filter_enabled(self.school_filter_enabled)
        if self.candidates:
            self.update_candidate_table()

    # ---------------- AI 状态 ----------------

    def refresh_ai_status(self):
        """刷新下载控制区的 AI 状态显示与匹配描述下拉框"""
        config = load_ai_config()
        has_key = bool(config.get("api_key"))
        enabled = bool(config.get("enabled")) and has_key
        self._refresh_match_desc_combo()
        if enabled:
            self.ai_enabled_label.setText("已启用")
            self.ai_enabled_label.setStyleSheet("color: #16A34A;")
        else:
            reason = "未配置" if not has_key else "未启用"
            self.ai_enabled_label.setText(reason)
            self.ai_enabled_label.setStyleSheet("color: #94A3B8;")

    def _refresh_match_desc_combo(self):
        """刷新下载控制区的匹配描述下拉框（自动/不使用/各岗位描述）"""
        try:
            self.match_desc_combo.blockSignals(True)
            self.match_desc_combo.clear()
            # 注意：qfluentwidgets ComboBox.addItem(text, icon=None, userData=None)，
            # 第二参数是 icon，userData 必须用关键字传，否则 currentData() 恒为 None
            self.match_desc_combo.addItem("自动匹配当前岗位", userData="__auto__")
            self.match_desc_combo.addItem("不使用AI筛选", userData="")
            config = load_ai_config()
            for name, desc in (config.get("job_descriptions", {}) or {}).items():
                if not name or not desc:
                    continue
                label = f"{name}：{desc[:24]}{'…' if len(desc) > 24 else ''}"
                self.match_desc_combo.addItem(label, userData=desc)
            idx = self.match_desc_combo.findData("__auto__")
            self.match_desc_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.match_desc_combo.blockSignals(False)
        except Exception:
            pass

    # ---------------- 职位/刷新 ----------------

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
        try:
            self.refresh_candidates()
        except Exception as e:
            self.log(f"自动刷新失败: {e}")

    # ---------------- 浏览器 ----------------

    def _is_chrome_port_open(self):
        """检测 Chrome 调试端口是否已开放"""
        try:
            return self.browser_controller.manager.is_debug_port_open()
        except Exception:
            return False

    def _on_browser_event(self, event_type, message):
        """浏览器事件回调（启动/重连/断开等）"""
        self.log(f"[浏览器] {message}")
        self.browser_state = self.browser_controller.browser_state()
        self._update_browser_status()

    def _on_monitor_status(self, state):
        """后台监控线程上报的浏览器状态"""
        self.browser_state = state
        self._update_browser_status()

    def _set_monitor_reconnect(self, allowed):
        """切换后台监控线程是否允许自动重连（任务运行期间关闭）"""
        self.browser_controller.set_monitor_reconnect(allowed)

    def _update_browser_status(self):
        """更新状态栏浏览器状态（优先使用后台监控线程上报的状态）"""
        from browser.browser_state import STATE_LABELS
        if self.browser_monitor is not None and self.browser_state:
            state = self.browser_state
        elif self.browser_controller.manager:
            state = self.browser_controller.browser_state()
        else:
            state = 'DISCONNECTED'
        self.browser_status_label.setText(STATE_LABELS.get(state, f"浏览器：{state}"))
        if state in ('CONNECTED', 'READY'):
            self.browser_status_label.setLevel(InfoLevel.SUCCESS)
        elif state in ('STARTING', 'CONNECTING', 'RECONNECTING'):
            self.browser_status_label.setLevel(InfoLevel.WARNING)
        else:
            self.browser_status_label.setLevel(InfoLevel.ERROR)

    def refresh_candidates(self, switch_job=''):
        """刷新候选人列表"""
        if self.browser_controller.is_worker_alive():
            self.log("正在获取中，请等待...")
            return

        if switch_job:
            self.log(f"正在切换职位并获取候选人列表...")
        else:
            self.log("正在连接浏览器并获取候选人列表...")

        if not self.browser_controller.collect_candidates_async(switch_job):
            self.log("浏览器连接失败或刷新启动失败")
            return

        self.set_buttons_enabled(False)
        self.current_task = 'refresh'
        self.browser_controller.set_monitor_reconnect(False)
        self.check_timer.start(500)

    # ---------------- 下载 ----------------

    def start_download(self):
        """开始下载"""
        selected = self.get_selected_candidates()
        if not selected:
            self.log("请先选择要下载的候选人")
            return

        if self.download_controller.is_worker_alive():
            self.log("有任务正在执行，请等待...")
            return

        download_dir = self.download_dir_edit.text()
        job_name = self.current_job
        ai_config = load_ai_config()
        download_all = self.download_all_check.isChecked()

        # 匹配描述：由用户从下拉框选择执行哪一个（默认自动匹配当前岗位）
        sel = self.match_desc_combo.currentData() if hasattr(self, 'match_desc_combo') else '__auto__'
        if sel == "":
            ai_config = None
            self.log("本次下载不使用 AI 筛选（已在下拉框选择）")
        elif ai_config.get("enabled") and ai_config.get("api_key"):
            job_descs = ai_config.get("job_descriptions", {})
            if sel == "__auto__":
                # 按当前职位查找匹配描述（精确 + 模糊）
                match_desc = job_descs.get(job_name, '')
                if not match_desc:
                    for key, desc in job_descs.items():
                        if key and desc and (key in job_name or job_name in key):
                            match_desc = desc
                            self.log(f"AI 匹配描述使用「{key}」的配置")
                            break
                if not match_desc:
                    self.log(f"警告: 当前职位「{job_name}」未配置匹配描述，AI 将按空描述评估（可在 设置→AI配置 中添加）")
            else:
                match_desc = sel
                self.log("AI 匹配描述：使用手动选择项")
            ai_config["match_description"] = match_desc
        else:
            ai_config = None

        # 防御：AI 启用但匹配描述为空时，明确阻止并提示（避免用空岗位要求静默评估）
        if ai_config and ai_config.get("enabled") and not (ai_config.get("match_description") or '').strip():
            self.log("错误: AI 筛选已启用，但当前没有可用的岗位匹配描述")
            self.log("请检查 AI 配置中的岗位名称是否与当前职位一致（或在下载区手动选择匹配描述）")
            QMessageBox.warning(
                self, "AI 匹配描述为空",
                "AI 筛选已启用，但没有找到当前职位的匹配描述。\n\n"
                "请在 设置→AI配置 中确认岗位名称与当前职位一致，\n"
                "或在下载控制区手动选择一条匹配描述后再开始下载。"
            )
            return
        if ai_config and ai_config.get("enabled"):
            desc = (ai_config.get("match_description") or "").strip()
            self.log(f"AI 匹配描述已生效: {desc[:60]}{'…' if len(desc) > 60 else ''}")

        # 同步创建数据库任务，确保 task_id 在下载子进程启动前可用
        task_id = self.task_controller.create_and_start(
            job_name=job_name,
            ai_config=ai_config,
            download_dir=download_dir,
            download_all=download_all,
            total=len(selected),
            candidate_list_url=self.current_page_url,
            selected_candidates=None if download_all else selected,
        )
        if not task_id:
            self.log("创建任务失败，无法开始下载")
            return
        self.current_task_id = task_id
        self.current_task_obj = self.task_controller.get_task(task_id)

        if download_all:
            self.log(f"开始下载所有页简历...")
        else:
            self.log(f"开始下载 {len(selected)} 个候选人简历...")

        # 显示中断按钮
        self.start_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setVisible(True)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setVisible(False)

        self.set_buttons_enabled(False)
        self.current_task = 'download'
        import time
        self.worker_start_time = time.time()

        if not self.download_controller.start(
            candidates=selected,
            download_dir=download_dir,
            job_name=job_name,
            ai_config=ai_config,
            download_all=download_all,
            task_id=task_id,
        ):
            self.log("下载进程启动失败")
            return
        self._set_monitor_reconnect(False)

        self.check_timer.start(500)
        self._update_task_status_label()

    def pause_download(self):
        """暂停下载：当前候选人完成后暂停"""
        self.download_controller.pause()
        self.log("已请求暂停，当前候选人处理完成后将暂停...")
        self.pause_btn.setEnabled(False)

    def on_resume_clicked(self):
        """点击继续任务"""
        try:
            if self.current_task_id:
                task = self.task_controller.get_task(self.current_task_id)
            else:
                unfinished = self.task_controller.get_unfinished_tasks()
                task = unfinished[0] if unfinished else None
            if task:
                self.resume_task(task)
            else:
                self.log("没有可恢复的任务")
                self.resume_btn.setVisible(False)
        except Exception as e:
            self.log(f"继续任务失败: {e}")

    def stop_download(self):
        """中断下载"""
        self.download_controller.stop()
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

    def _update_task_status_label(self):
        """更新状态栏任务状态"""
        if self.current_task == 'download' and self.download_controller.is_worker_alive():
            text = "任务状态：运行中"
            if self.current_task_id:
                try:
                    task = self.task_controller.get_task(self.current_task_id)
                    if task:
                        text = f"任务状态：运行中 {task.processed_count}/{task.total_candidates} · 第{task.current_page}页"
                except Exception:
                    pass
            self.task_status_label.setText(text)
            self.task_status_label.setLevel(InfoLevel.INFOAMTION)
        elif self.current_task == 'refresh':
            self.task_status_label.setText("任务状态：刷新中")
            self.task_status_label.setLevel(InfoLevel.INFOAMTION)
        elif self.current_task_id or self.last_task_id:
            try:
                task = self.task_controller.get_task(self.current_task_id or self.last_task_id)
                if task:
                    status_text = {
                        'running': '运行中',
                        'paused': '已暂停',
                        'completed': '已完成',
                        'failed': '失败',
                        'cancelled': '已取消',
                    }.get(task.status, task.status)
                    self.task_status_label.setText(f"任务状态：{status_text}")
                    self.task_status_label.setLevel(
                        InfoLevel.INFOAMTION if task.status == 'running' else
                        InfoLevel.WARNING if task.status == 'paused' else
                        InfoLevel.SUCCESS if task.status == 'completed' else
                        InfoLevel.ERROR if task.status == 'failed' else InfoLevel.INFOAMTION
                    )
                    return
            except Exception:
                pass
            self.task_status_label.setText("任务状态：空闲")
            self.task_status_label.setLevel(InfoLevel.INFOAMTION)
        else:
            self.task_status_label.setText("任务状态：空闲")
            self.task_status_label.setLevel(InfoLevel.INFOAMTION)

    def _run_db_thread(self, func, *args, **kwargs):
        """
        安全地启动数据库后台线程。

        持有线程引用直到 finished，避免 QThread 被垃圾回收时线程仍在运行，
        导致 Qt abort 闪退。
        """
        thread = DBWorkerThread(self.db, func, *args, **kwargs)
        self._db_threads.append(thread)

        def _on_finished():
            if thread in self._db_threads:
                self._db_threads.remove(thread)

        thread.finished.connect(_on_finished)
        thread.start()
        return thread

    def _animate_progress(self, value, total):
        """平滑更新任务进度条"""
        if not total or total <= 0:
            self.progress_bar.setVisible(False)
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, int(total))
        anim = QPropertyAnimation(self.progress_bar, b"value", self)
        anim.setDuration(250)
        anim.setStartValue(self.progress_bar.value())
        anim.setEndValue(max(0, min(int(value), int(total))))
        anim.start()
        self._progress_anim = anim  # 持有引用，防止动画被 GC

    def check_worker_status(self):
        """检查子进程状态（refresh 归 BrowserController，download 归 DownloadController）"""
        try:
            self._update_task_status_label()

            # 浏览器监控由后台线程负责：任务运行期间关闭自动重连，空闲时自动恢复
            self._set_monitor_reconnect(
                not (self.browser_controller.is_worker_alive()
                     or self.download_controller.is_worker_alive())
            )

            # 无任务：不读取任何 worker queue，直接清理返回
            if self.current_task is None:
                self._reset_task_ui()
                return

            # ---- refresh 分支：BrowserController 管理 ----
            if self.current_task == 'refresh':
                if self.browser_controller.is_worker_alive():
                    # 看门狗：超过90秒无结果则终止，避免界面卡死
                    if self.browser_controller.refresh_elapsed() > 90:
                        self.log("刷新超时，已终止该次获取，请重试")
                        self.browser_controller.kill_worker()
                        self._reset_task_ui()
                    return

                result = self.browser_controller.poll_result()
                if result is not None:
                    self._on_refresh_finished(result)
                else:
                    self.log("任务失败：无结果")
                self.browser_controller.kill_worker()
                self._reset_task_ui()
                return

            # ---- download 分支：DownloadController 管理 ----
            if self.current_task == 'download':
                if self.download_controller.is_worker_alive():
                    # 下载中实时更新进度条（平滑动画）
                    if self.current_task_id:
                        try:
                            task = self.task_controller.get_task(self.current_task_id)
                            if task and task.total_candidates:
                                self._animate_progress(task.processed_count, task.total_candidates)
                        except Exception:
                            pass
                    return

                result = self.download_controller.poll_result()
                if result is not None:
                    self._on_download_finished(result)
                    if result.get('paused') or result.get('login_expired'):
                        self.resume_btn.setVisible(True)
                        self.resume_btn.setEnabled(True)
                    else:
                        self.resume_btn.setVisible(False)
                else:
                    self.log("任务失败：无结果")
                self._reset_task_ui()
                return

        except Exception as e:
            import traceback
            self.log(f"检查任务状态异常: {e}")
            traceback.print_exc()
            self._reset_task_ui()

    def _reset_task_ui(self):
        """任务结束统一清理：停 timer、隐藏进度、恢复按钮、清 current_task（幂等）"""
        self.check_timer.stop()
        self.progress_bar.setVisible(False)
        self.set_buttons_enabled(True)
        self.start_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.pause_btn.setVisible(False)
        self.current_task = None
        self.worker_start_time = None
        self._update_task_status_label()

    def _on_refresh_finished(self, result):
        """刷新完成回调"""
        try:
            if not result.get('success'):
                error = result.get('error', '未知错误')
                self.log(f"获取失败: {error}")
                if result.get('login_status') == 'expired':
                    self.log("前程无忧登录状态已失效，请重新登录后刷新")
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
            self.current_page_url = result.get('page_url', '') or self.current_page_url
            self.page_type = result.get('page_type', '')
            self.login_status = result.get('login_status', '')

            candidates = result.get('candidates', [])
            # 关联历史记录：已下载/AI淘汰自动过滤，下载失败保留并显示记录
            kept, filter_counts = self._load_candidate_history(candidates)
            self.candidates = kept
            if filter_counts['downloaded'] or filter_counts['ai_rejected']:
                self.log(
                    f"已过滤 {filter_counts['downloaded']} 个已下载、"
                    f"{filter_counts['ai_rejected']} 个AI淘汰候选人"
                )
            self.update_candidate_table()

            total = len(kept)
            if self.school_filter_enabled:
                filtered = sum(
                    1 for c in kept
                    if self.candidate_service.is_school_allowed(c.get('school', ''))
                )
                self.log(
                    f"获取到 {len(candidates)} 个候选人，历史过滤后 {total} 个，"
                    f"学校筛选后 {filtered} 个"
                )
            else:
                self.log(f"获取到 {len(candidates)} 个候选人，历史过滤后 {total} 个")

            self.candidate_count_label.setText(f"候选人: {total}")

            # 启用开始下载按钮
            if candidates:
                self.start_btn.setEnabled(True)

            # 检查是否有未完成的任务
            if not self._unfinished_checked:
                QTimer.singleShot(500, self.check_unfinished_tasks)
        except Exception as e:
            import traceback
            self.log(f"处理刷新结果异常: {e}")
            traceback.print_exc()

    def _load_candidate_history(self, candidates):
        """
        按候选人 external_id 查询历史处理记录。

        Returns:
            (保留的候选人列表, {'downloaded': n, 'ai_rejected': n})
            已下载 / AI淘汰 的候选人被过滤；失败/有失败原因的保留并展示记录。
        """
        self.candidate_service.load_history(candidates)
        kept, counts = self.candidate_service.filter_by_history(candidates)
        if self.candidate_service.history:
            self.log(f"{len(self.candidate_service.history)} 个候选人存在历史处理记录")
        return kept, counts

    def _startup_check_unfinished(self):
        """启动时检查未完成任务（不依赖刷新成功）"""
        try:
            self.check_unfinished_tasks()
        except Exception as e:
            print(f"启动检查未完成任务失败: {e}")

    def _async_sync_jobs(self, positions):
        """异步同步岗位到数据库"""
        def do_sync():
            try:
                self.job_service.sync_jobs(positions)
            except Exception as e:
                print(f"同步岗位失败: {e}")

        self._run_db_thread(do_sync)

    def check_unfinished_tasks(self):
        """检查是否有未完成的任务"""
        if getattr(self, '_unfinished_checked', False):
            return
        self._unfinished_checked = True
        try:
            unfinished = self.task_controller.get_unfinished_tasks()
            if unfinished:
                task = unfinished[0]
                stats = self.task_controller.get_task_stats(task.id)
                browser_text, login_text = self._get_browser_login_status()
                msg = QMessageBox(self)
                msg.setWindowTitle("恢复任务")
                msg.setText(
                    "发现未完成的任务：\n\n"
                    f"岗位：{task.job_name}\n"
                    f"进度：{task.processed_count} / {task.total_candidates}\n"
                    f"当前页：第 {task.current_page} 页\n"
                    f"已下载：{stats.get('success', 0)}\n"
                    f"AI淘汰：{stats.get('ai_fail', 0)}\n\n"
                    f"浏览器：{browser_text}\n"
                    f"登录状态：{login_text}\n\n"
                    "继续任务前会检查浏览器、登录状态与岗位匹配。"
                )
                resume_btn = msg.addButton("继续任务", AcceptRole)
                abandon_btn = msg.addButton("放弃任务", DestructiveRole)
                msg.addButton("稍后", RejectRole)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked == resume_btn:
                    self.resume_task(task)
                elif clicked == abandon_btn:
                    self.task_controller.cancel_task(task.id, '用户放弃任务')
                    self.log(f"已放弃任务 #{task.id}")
        except Exception as e:
            print(f"检查未完成任务失败: {e}")

    def _get_browser_login_status(self):
        """获取 GUI 侧浏览器/登录状态文本（用于恢复任务对话框）"""
        from browser.browser_state import STATE_LABELS
        browser_text = '未连接'
        login_text = '未知'
        try:
            mgr = self.browser_controller.manager
            state = mgr.state if mgr else 'DISCONNECTED'
            browser_text = STATE_LABELS.get(state, state)
            status = self.browser_controller.get_login_status()
            login_text = {
                'logged_in': '正常',
                'expired': '已失效',
                'unknown': '未知',
            }.get(status, '未知')
        except Exception:
            pass
        return browser_text, login_text

    def resume_task(self, task):
        """恢复任务"""
        try:
            # 1. 浏览器检查
            if not self.browser_controller.ensure_ready():
                self.log(f"浏览器连接失败，无法恢复任务: {self.browser_controller.manager.last_error}")
                return
            page = self.browser_controller.get_page()
            if not page:
                self.log("未找到浏览器页面，无法恢复任务")
                return

            # 2. 登录状态检查
            login_status = self.browser_controller.get_login_status()
            if login_status == 'expired':
                self.log("前程无忧登录状态已失效，请重新登录后点击“继续任务”")
                self.task_controller.pause_task(task.id, '登录状态失效')
                self.resume_btn.setVisible(True)
                self.resume_btn.setEnabled(True)
                return

            # 3. 页面类型检查（必须是候选人列表/职位列表页）
            page_type = self.browser_controller.get_page_type()
            if page_type not in ('CANDIDATE_LIST_PAGE', 'JOB_LIST_PAGE'):
                self.log(f"当前页面不是候选人列表页（{page_type}），请先在 Chrome 中打开人才管理页面")
                self.resume_btn.setVisible(True)
                self.resume_btn.setEnabled(True)
                return

            # 4. 岗位匹配检查
            current_job = self.browser_controller.get_current_job()
            if current_job and task.job_name and current_job != task.job_name:
                reply = QMessageBox.question(
                    self, "岗位不匹配",
                    f"当前 Chrome 岗位：{current_job}\n"
                    f"任务岗位：{task.job_name}\n\n"
                    "是否切换到任务岗位后继续？",
                    MessageBoxYes | MessageBoxNo
                )
                if reply != MessageBoxYes:
                    self.log("岗位不匹配，任务保持暂停")
                    return
                if not self.browser_controller.switch_job(task.job_name):
                    self.log("切换岗位失败，请手动在 Chrome 中切换后重试")
                    return
                import time as _t
                _t.sleep(5)
                page = self.browser_controller.get_page()
                if page and self.browser_controller.get_current_job() != task.job_name:
                    self.log("岗位切换未生效，请手动切换后重试")
                    return

            # 5. 定位任务当前页
            if page and task.current_page and task.current_page > 1:
                self.browser_controller.go_to_page(task.current_page)
                import time as _t
                _t.sleep(2)
                page = self.browser_controller.get_page()

            # 6. 获取可恢复候选人（pending/processing/failed，跳过已下载/已淘汰）
            recoverable = self.task_controller.get_recoverable_candidates(task.id)
            if not recoverable:
                self.log(f"任务 #{task.id} 没有待处理的候选人，标记为完成")
                self.task_controller.complete_task(task.id)
                self.resume_btn.setVisible(False)
                return

            # 标记任务为运行中
            self.task_controller.resume_task(task.id)
            self.current_task_id = task.id
            self.current_task_obj = task

            # 恢复下载配置
            self.job_combo.setCurrentText(task.job_name)
            download_dir = task.download_dir or str(_BASE_DIR / "output" / "resumes")
            self.download_dir_edit.setText(download_dir)

            # 从任务快照恢复 AI 配置
            ai_config = None
            snapshot = self.task_controller.get_task(task.id)
            restored = self.task_controller.restore_ai_config(snapshot)
            if restored.get('enabled') and restored.get('api_key'):
                ai_config = restored
            elif task.ai_enabled and task.ai_api_key:
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
                    "sort_index": c.sort_index,
                    "external_id": c.candidate_external_id,
                }
                for c in recoverable
            ]

            self.log(f"恢复任务 #{task.id}: {task.job_name}，待处理 {len(candidates)} 个候选人")
            self.log("已完成浏览器/登录/岗位校验")

            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(True)
            self.stop_btn.setEnabled(True)
            self.pause_btn.setVisible(True)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setVisible(False)

            self.set_buttons_enabled(False)
            self.current_task = 'download'
            import time
            self.worker_start_time = time.time()

            if not self.download_controller.start(
                candidates=candidates,
                download_dir=download_dir,
                job_name=task.job_name,
                ai_config=ai_config,
                download_all=False,
                task_id=task.id,
            ):
                self.log("下载进程启动失败")
                return
            self._set_monitor_reconnect(False)
            self.check_timer.start(500)
            self._update_task_status_label()
        except Exception as e:
            import traceback
            self.log(f"恢复任务失败: {e}")
            traceback.print_exc()

    def _on_download_finished(self, result):
        """下载完成回调"""
        try:
            if not result.get('success'):
                error = result.get('error', '未知错误')
                if result.get('login_expired'):
                    self.log("前程无忧登录状态已失效，任务已暂停。请重新登录后点击“继续任务”。")
                    self.last_task_id = self.current_task_id
                    self.current_task_id = None
                    self.task_controller.update_task_complete(
                        self.last_task_id, 1, 0, 0, paused=True
                    )
                elif result.get('paused'):
                    self.log(f"任务已暂停: {error}")
                    self.last_task_id = self.current_task_id
                    self.current_task_id = None
                    self.task_controller.update_task_complete(
                        self.last_task_id, 1, 0, 0, paused=True
                    )
                else:
                    self.log(f"下载失败: {error}")
                    self.last_task_id = self.current_task_id
                    self.current_task_id = None
                    self.task_controller.update_task_failed(self.last_task_id, error)
                return
            results = result.get('results', [])
            success_count = sum(1 for r in results if r.get('success'))
            fail_count = len(results) - success_count
            total_pages = result.get('total_pages', 1)

            self.log(f"下载完成: 成功 {success_count} 个，失败 {fail_count} 个，共 {total_pages} 页")

            # 异步更新数据库任务状态
            paused = (self.download_controller.is_stopped()
                      or self.download_controller.is_pause_requested()
                      or result.get('paused', False))
            self.download_controller.clear_events()
            self.last_task_id = self.current_task_id
            self.current_task_id = None
            self.task_controller.update_task_complete(
                self.last_task_id, total_pages, success_count, fail_count, paused=paused
            )

            # 导出结果
            if results:
                self.export_results(results)
        except Exception as e:
            import traceback
            self.log(f"处理下载结果异常: {e}")
            traceback.print_exc()

    def export_results(self, results):
        """导出下载结果"""
        try:
            excel_path = self.candidate_service.export_excel(
                results,
                self.current_job,
                self.download_dir_edit.text(),
            )
            self.log(f"结果已导出: {excel_path}")
        except Exception as e:
            self.log(f"导出结果失败: {e}")

    # ---------------- 候选人表格 ----------------

    def update_candidate_table(self):
        """更新候选人表格"""
        display_candidates = []
        for c in self.candidates:
            if self.school_filter_enabled:
                if self.candidate_service.is_school_allowed(c.get('school', '')):
                    display_candidates.append(c)
            else:
                display_candidates.append(c)

        self.candidate_table.clearSpans()
        if not display_candidates:
            # 空状态提示
            self.candidate_table.setRowCount(1)
            empty_item = QTableWidgetItem("暂无候选人，请点击“刷新列表”获取")
            empty_item.setTextAlignment(AlignCenter)
            empty_item.setForeground(QColor(148, 163, 184))
            self.candidate_table.setSpan(0, 0, 1, 6)
            self.candidate_table.setItem(0, 0, empty_item)
            return

        self.candidate_table.setRowCount(len(display_candidates))

        for i, candidate in enumerate(display_candidates):
            checkbox = FluentCheckBox()
            checkbox.setChecked(True)
            self.candidate_table.setCellWidget(i, 0, checkbox)

            name = candidate.get('name', '')
            self.candidate_table.setItem(i, 1, QTableWidgetItem(name))

            school = candidate.get('school', '')
            school_item = QTableWidgetItem(school)
            if school and not self.candidate_service.is_school_allowed(school):
                school_item.setForeground(QColor(255, 0, 0))
            self.candidate_table.setItem(i, 2, school_item)

            major = candidate.get('major', '')
            self.candidate_table.setItem(i, 3, QTableWidgetItem(major))

            education = candidate.get('education', '')
            self.candidate_table.setItem(i, 4, QTableWidgetItem(education))

            # 处理记录列（历史下载结果/失败原因）
            record = self.candidate_service.get_history_for(candidate)
            if record['text']:
                dot_colors = {
                    '失败': '#DC2626',
                    '已下载': '#16A34A',
                    'AI淘汰': '#D97706',
                }.get(record['text'], '#94A3B8')
                text_color = (
                    f"rgb({record['color'][0]},{record['color'][1]},{record['color'][2]})"
                    if record['color'] else '#334155'
                )
                badge = QLabel(
                    f'<span style="color:{dot_colors};font-size:9px;">●</span> '
                    f'<span style="color:{text_color};">{html.escape(record["text"])}</span>'
                )
                badge.setToolTip(record['tooltip'])
                badge.setAlignment(AlignCenter)
                self.candidate_table.setCellWidget(i, 5, badge)
            else:
                self.candidate_table.setItem(i, 5, QTableWidgetItem(''))

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

    # ---------------- 日志 ----------------

    def log(self, message, level='info'):
        """写入操作日志（按级别/关键词着色）"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        if level == 'error' or any(k in message for k in ('失败', '错误', '异常')):
            color = '#DC2626'
        elif level == 'success' or any(k in message for k in ('成功', '完成')):
            color = '#16A34A'
        elif level == 'warning' or any(k in message for k in ('警告', '注意')):
            color = '#D97706'
        else:
            color = '#334155'
        safe = html.escape(message)
        self.log_text.append(
            f'<span style="color:#94A3B8">[{timestamp}]</span> '
            f'<span style="color:{color}">{safe}</span>'
        )

    def clear_log(self):
        self.log_text.clear()
