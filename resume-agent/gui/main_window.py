# -*- coding: utf-8 -*-
"""
主窗口模块 - AI 简历批量初筛与下载助手
"""
import sys
import os
import json
import html
import multiprocessing
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
    QToolBar, QStatusBar, QMenuBar, QHeaderView, QCheckBox,
    QPushButton, QLabel, QGroupBox, QGridLayout,
    QLineEdit, QDialog, QMessageBox, QProgressBar, QApplication,
    QFileDialog, QComboBox, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QEvent, QPropertyAnimation, QPoint
from PyQt6.QtGui import QAction, QFont, QColor, QIcon, QShortcut, QKeySequence

# 获取基础目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent

sys.path.insert(0, str(_BASE_DIR))
from config import load_ai_config, save_ai_config
from db import Database


def _resource_dir() -> Path:
    """
    资源目录：源码模式为项目目录；打包后为 PyInstaller 解压目录 _MEIPASS。
    （QSS/SVG 通过 spec 的 datas 打进 _MEIPASS，而不是 exe 同级目录）
    """
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
    return _BASE_DIR


def refresh_worker_target(queue, switch_job):
    """刷新候选人子进程目标函数"""
    try:
        from browser_worker import run
        result = run(switch_job)
        queue.put(result)
    except Exception as e:
        queue.put({'success': False, 'error': str(e)})


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
        self.current_page_url = ""          # 当前候选人列表URL（存入任务）
        self.page_type = ''                 # 当前页面类型（PageDetector）
        self.login_status = ''              # 当前登录状态
        self.candidate_history = {}         # 候选人历史处理记录（external_id -> record）
        
        # 数据库
        self.db = Database()
        self._db_threads = []           # 持有 DB 后台线程引用，防止 QThread 被 GC 导致闪退
        self.current_task_id = None
        self.last_task_id = None
        self.current_task_obj = None
        self.current_task = None
        
        # 浏览器管理（GUI侧状态显示与健康检查）
        self.browser_manager = None
        self.browser_state = 'DISCONNECTED'
        self.health_check_ticks = 0
        
        # 跨进程中断信号
        self.stop_event = multiprocessing.Event()
        self.pause_event = multiprocessing.Event()

        self.setWindowTitle("AI 简历批量初筛与下载助手")
        self.setMinimumSize(960, 620)

        # 无边框窗口（圆角卡片 + 纯色背景；不使用 WA_TranslucentBackground，
        # 避免部分机器上透明区域渲染为黑色/不可点击）
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.theme = 'light'

        self.apply_theme('light')
        self.setup_ui()
        self.setup_menu()
        self.setup_toolbar()
        self.setup_statusbar()

        # 根据已保存的 AI 配置刷新状态显示（否则重启后一直显示“未配置”）
        self._update_ai_status()

        # 定时器检查子进程状态
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_worker_status)
        self.result_queue = None
        self.worker_start_time = None
        self._progress_anim = None

        # 快捷键
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_candidates)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.start_download)

        # 尝试加载上次的学校名单
        self.load_last_school_list()

        # 启动后自动尝试连接浏览器（带端口检测，避免启动崩溃）
        # RA_NO_AUTO_REFRESH=1 时跳过（用于开发/截图调试）
        if os.environ.get("RA_NO_AUTO_REFRESH") != "1":
            QTimer.singleShot(500, self.auto_refresh)
            # 启动时检测未完成任务（无论刷新是否成功，方案第 22 节）
            self._unfinished_checked = False
            QTimer.singleShot(3000, self._startup_check_unfinished)
        else:
            self._unfinished_checked = True

    def apply_theme(self, theme='light'):
        """应用主题样式（light / dark）"""
        self.theme = theme
        try:
            # 亮色主题文件名为 default.qss
            style_name = 'default.qss' if theme == 'light' else f'{theme}.qss'
            style_path = _resource_dir() / "gui" / "resources" / "styles" / style_name
            if style_path.exists():
                with open(style_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
        except Exception:
            pass
        try:
            if hasattr(self, 'dark_theme_action'):
                self.dark_theme_action.setChecked(theme == 'dark')
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
        # 根窗口：容器铺满，无外层边距（避免“窗口外背景层”与缩放边缘错位）
        root_widget = QWidget()
        self._root_layout = QVBoxLayout(root_widget)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(root_widget)

        # 容器：标题栏 + 菜单 + 工具栏 + 内容 + 状态栏
        from gui.widgets.title_bar import TitleBar
        self.window_container = QFrame()
        self.window_container.setObjectName("windowContainer")
        self._container_layout = QVBoxLayout(self.window_container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)

        self.title_bar = TitleBar(self.window_container)
        self._container_layout.addWidget(self.title_bar)

        central_widget = QWidget()
        self._container_layout.addWidget(central_widget, 1)
        self._root_layout.addWidget(self.window_container)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)

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
        self.candidate_table.setColumnCount(6)
        self.candidate_table.setHorizontalHeaderLabels(["选择", "姓名", "学校", "专业", "学历", "处理记录"])
        self.candidate_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.candidate_table.setAlternatingRowColors(True)
        left_layout.addWidget(self.candidate_table)

        splitter.addWidget(left_widget)

        # 右侧：控制面板和日志
        right_widget = QWidget()
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

        control_layout.addWidget(QLabel("匹配描述:"), 3, 0)
        self.match_desc_combo = QComboBox()
        self.match_desc_combo.setToolTip("选择本次下载使用的岗位匹配描述（默认自动匹配当前岗位）")
        control_layout.addWidget(self.match_desc_combo, 3, 1)

        # 下载按钮布局
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始下载")
        self.start_btn.setIcon(self._icon("play"))
        self.start_btn.clicked.connect(self.start_download)
        self.start_btn.setEnabled(False)

        self.stop_btn = QPushButton("中断下载")
        self.stop_btn.setIcon(self._icon("stop"))
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)

        self.pause_btn = QPushButton("暂停下载")
        self.pause_btn.setIcon(self._icon("pause"))
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setVisible(False)

        self.resume_btn = QPushButton("继续任务")
        self.resume_btn.setIcon(self._icon("resume"))
        self.resume_btn.clicked.connect(self.on_resume_clicked)
        self.resume_btn.setEnabled(False)
        self.resume_btn.setVisible(False)

        self.download_all_check = QCheckBox("下载所有页")
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
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_btn_layout.addWidget(self.clear_log_btn)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)

        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group, 1)

        splitter.addWidget(right_widget)
        splitter.setSizes([700, 500])
        main_layout.addWidget(splitter)

    def setup_menu(self):
        # 菜单栏放入容器内（无边框窗口不使用 QMainWindow 原生菜单栏）
        menubar = QMenuBar(self.window_container)
        menubar.setObjectName("appMenuBar")
        self._container_layout.insertWidget(1, menubar)

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

        self.dark_theme_action = QAction("暗色主题", self)
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.setChecked(self.theme == 'dark')
        self.dark_theme_action.toggled.connect(
            lambda checked: self.apply_theme('dark' if checked else 'light')
        )
        settings_menu.addAction(self.dark_theme_action)

        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_toolbar(self):
        toolbar = QToolBar("工具栏", self.window_container)
        self._container_layout.insertWidget(2, toolbar)

        self.toolbar_refresh_btn = QPushButton("刷新列表")
        self.toolbar_refresh_btn.setIcon(self._icon("refresh"))
        self.toolbar_refresh_btn.clicked.connect(self.refresh_candidates)
        toolbar.addWidget(self.toolbar_refresh_btn)

    @staticmethod
    def _icon(name):
        """加载 SVG 图标"""
        icon_path = _resource_dir() / "gui" / "resources" / "icons" / f"{name}.svg"
        return QIcon(str(icon_path)) if icon_path.exists() else QIcon()

    def setup_statusbar(self):
        # 状态栏放入容器内
        self._statusbar = QStatusBar(self.window_container)
        self._statusbar.setObjectName("appStatusBar")
        self._statusbar.showMessage("就绪")

        self.candidate_count_label = QLabel("候选人: 0")
        self.download_count_label = QLabel("已下载: 0")
        self.ai_status_label = QLabel('<span style="color:#94A3B8">●</span> AI: 未配置')
        self.browser_status_label = QLabel('<span style="color:#94A3B8">●</span> 浏览器：未连接')
        self.task_status_label = QLabel('<span style="color:#94A3B8">●</span> 任务状态：空闲')

        self._statusbar.addPermanentWidget(self.candidate_count_label)
        self._statusbar.addPermanentWidget(self.download_count_label)
        self._statusbar.addPermanentWidget(self.ai_status_label)
        self._statusbar.addPermanentWidget(self.browser_status_label)
        self._statusbar.addPermanentWidget(self.task_status_label)
        self._container_layout.addWidget(self._statusbar)

    def _update_ai_status(self):
        """根据已保存的 AI 配置刷新“AI筛选”与状态栏显示"""
        config = load_ai_config()
        has_key = bool(config.get("api_key"))
        enabled = bool(config.get("enabled")) and has_key
        self._refresh_match_desc_combo()
        if enabled:
            self.ai_enabled_label.setText("已启用")
            self.ai_enabled_label.setStyleSheet("color: #16A34A;")
            self.ai_status_label.setText('<span style="color:#16A34A">●</span> AI: 已启用')
            self.ai_status_label.setStyleSheet("color: green;")
        else:
            reason = "未配置" if not has_key else "未启用"
            self.ai_enabled_label.setText(reason)
            self.ai_enabled_label.setStyleSheet("color: #94A3B8;")
            self.ai_status_label.setText(f'<span style="color:#94A3B8">●</span> AI: {reason}')
            self.ai_status_label.setStyleSheet("color: gray;")

    def _refresh_match_desc_combo(self):
        """刷新下载控制区的匹配描述下拉框（自动/不使用/各岗位描述）"""
        try:
            self.match_desc_combo.blockSignals(True)
            self.match_desc_combo.clear()
            self.match_desc_combo.addItem("自动匹配当前岗位", "__auto__")
            self.match_desc_combo.addItem("不使用AI筛选", "")
            config = load_ai_config()
            for name, desc in (config.get("job_descriptions", {}) or {}).items():
                if not name or not desc:
                    continue
                label = f"{name}：{desc[:24]}{'…' if len(desc) > 24 else ''}"
                self.match_desc_combo.addItem(label, desc)
            idx = self.match_desc_combo.findData("__auto__")
            self.match_desc_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.match_desc_combo.blockSignals(False)
        except Exception:
            pass

    # ==================== 无边框窗口 ====================

    def _update_window_chrome(self):
        """窗口状态变化处理（无外阴影/边距；仅同步容器状态与图标）"""
        maximized = self.isMaximized()
        self.window_container.setProperty("maximized", "true" if maximized else "false")
        style = self.window_container.style()
        style.unpolish(self.window_container)
        style.polish(self.window_container)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            try:
                self.title_bar.on_window_state_changed(self.windowState())
            except Exception:
                pass
            self._update_window_chrome()
            if maximized:
                screen = self.screen()
                if screen:
                    self.setGeometry(screen.availableGeometry())

    def nativeEvent(self, eventType, message):
        """
        Windows 无边框窗口边缘缩放支持（WM_NCHITTEST）。

        注意：PyQt6 6.11 在此系统上，覆写 nativeEvent 后再调用
        super().nativeEvent() 会触发 QtCore.pyd 访问违例（闪退）。
        因此本方法一律不调用 super，未处理的 Windows 消息统一返回
        (False, 0)，交给 Qt 默认处理。
        """
        try:
            if eventType == b"windows_generic_MSG" and not self.isMaximized() and not self.isFullScreen():
                import ctypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

                    # 边缘缩放优先（窗口边缘 8px 内可拖拽调整大小）
                    g = self.geometry()
                    border = 8
                    left = x <= g.left() + border
                    right = x >= g.right() - border
                    top = y <= g.top() + border
                    bottom = y >= g.bottom() - border
                    if left and top:
                        return True, 13   # HTTOPLEFT
                    if right and top:
                        return True, 14   # HTTOPRIGHT
                    if left and bottom:
                        return True, 16   # HTBOTTOMLEFT
                    if right and bottom:
                        return True, 17   # HTBOTTOMRIGHT
                    if left:
                        return True, 10   # HTLEFT
                    if right:
                        return True, 11   # HTRIGHT
                    if top:
                        return True, 12   # HTTOP
                    if bottom:
                        return True, 15   # HTBOTTOM

                    # 标题栏区域：返回 HTCAPTION 交给系统原生拖动（按钮区域除外）
                    local = self.mapFromGlobal(QPoint(x, y))
                    tb = getattr(self, 'title_bar', None)
                    if tb is not None and local.y() > border and tb.geometry().contains(local):
                        tb_local = tb.mapFromGlobal(QPoint(x, y))
                        under = tb.childAt(tb_local)
                        if under not in (getattr(tb, 'min_btn', None),
                                         getattr(tb, 'max_btn', None),
                                         getattr(tb, 'close_btn', None)):
                            return True, 2   # HTCAPTION
            return False, 0
        except Exception:
            return False, 0

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
            return self._get_browser_manager().is_debug_port_open()
        except Exception:
            return False

    def _get_browser_manager(self):
        """获取 GUI 侧 BrowserManager（状态显示/健康检查用）"""
        if self.browser_manager is None:
            from browser.browser_manager import BrowserManager
            self.browser_manager = BrowserManager(on_event=self._on_browser_event)
        return self.browser_manager

    def _on_browser_event(self, event_type, message):
        """浏览器事件回调（启动/重连/断开等）"""
        self.log(f"[浏览器] {message}")
        self._update_browser_status()

    def _update_browser_status(self):
        """更新状态栏浏览器状态"""
        from browser.browser_state import STATE_LABELS
        state = self.browser_manager.state if self.browser_manager else 'DISCONNECTED'
        self.browser_state = state
        dot = {
            'CONNECTED': '#16A34A', 'READY': '#16A34A',
            'STARTING': '#F59E0B', 'CONNECTING': '#F59E0B', 'RECONNECTING': '#F59E0B',
            'ERROR': '#DC2626',
        }.get(state, '#94A3B8')
        self.browser_status_label.setText(
            f'<span style="color:{dot}">●</span> {STATE_LABELS.get(state, f"浏览器：{state}")}'
        )
        if state in ('CONNECTED', 'READY'):
            self.browser_status_label.setStyleSheet("color: green;")
        elif state in ('STARTING', 'CONNECTING', 'RECONNECTING'):
            self.browser_status_label.setStyleSheet("color: orange;")
        else:
            self.browser_status_label.setStyleSheet("color: red;")

    def _ensure_chrome_debug(self):
        """确保 Chrome 调试模式已启动，未启动则自动启动"""
        mgr = self._get_browser_manager()
        if mgr.health_check():
            self._update_browser_status()
            return True
        try:
            self.log("未检测到 Chrome 调试模式，正在自动启动 Chrome...")
            if mgr.initialize(auto_launch=True):
                self.log("Chrome 调试模式已启动")
                self._update_browser_status()
                return True
            self.log("Chrome 调试模式启动失败或超时，请检查 Chrome 是否已安装")
            self._update_browser_status()
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

        # 重置中断信号
        self.stop_event.clear()
        self.pause_event.clear()

        # 同步创建数据库任务，确保 task_id 在下载子进程启动前可用
        task_id = self._create_task_and_candidates(
            job_name, ai_config, download_dir, download_all, len(selected)
        )
        if not task_id:
            self.log("创建任务失败，无法开始下载")
            return

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

        self.result_queue = multiprocessing.Queue()

        # 传递 stop_event 与 task_id 给子进程
        self.worker_process = multiprocessing.Process(
            target=download_worker_target,
            args=(self.result_queue, selected, download_dir, job_name, 
                  ai_config, download_all, self.stop_event, task_id,
                  self.pause_event),
            daemon=True
        )
        self.worker_process.start()

        self.check_timer.start(500)
        self._update_task_status_label()
    
    def _create_task_and_candidates(self, job_name, ai_config, download_dir, download_all, total):
        """同步创建数据库任务并写入候选人记录，返回 task_id"""
        try:
            from task import TaskManager
            tm = TaskManager()
            task = tm.create_task(
                job_name=job_name,
                ai_config=ai_config if ai_config else {},
                download_dir=download_dir,
                download_all_pages=download_all,
                total_candidates=total,
                candidate_list_url=self.current_page_url,
            )
            self.current_task_id = task.id
            self.current_task_obj = task
            tm.start_task(task.id)
            # 单页模式预写入选中候选人；分页模式由下载进程按页补充
            if not download_all:
                candidates = self.get_selected_candidates()
                tm.db.add_candidates_batch(
                    task.id,
                    [dict(c, page=1, sort_index=i) for i, c in enumerate(candidates)]
                )
            tm.log(task.id, 'task_log', f'开始下载 {total} 个候选人')
            return task.id
        except Exception as e:
            self.log(f"创建任务失败: {e}")
            print(f"创建任务失败: {e}")
            return None

    def pause_download(self):
        """暂停下载：当前候选人完成后暂停（方案第 27 节）"""
        self.pause_event.set()
        self.log("已请求暂停，当前候选人处理完成后将暂停...")
        self.pause_btn.setEnabled(False)

    def on_resume_clicked(self):
        """点击继续任务"""
        try:
            if self.current_task_id:
                task = self.db.get_task(self.current_task_id)
            else:
                unfinished = self.db.get_unfinished_tasks()
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

    def _update_task_status_label(self):
        """更新状态栏任务状态（方案第 29 节）"""
        dot_green = '<span style="color:#16A34A">●</span> '
        dot_blue = '<span style="color:#2563EB">●</span> '
        dot_orange = '<span style="color:#F59E0B">●</span> '
        dot_gray = '<span style="color:#94A3B8">●</span> '
        if self.current_task == 'download' and self.worker_process and self.worker_process.is_alive():
            text = "任务状态：运行中"
            if self.current_task_id:
                try:
                    task = self.db.get_task(self.current_task_id)
                    if task:
                        text = f"任务状态：运行中 {task.processed_count}/{task.total_candidates} · 第{task.current_page}页"
                except Exception:
                    pass
            self.task_status_label.setText(dot_blue + text)
            self.task_status_label.setStyleSheet("color: blue;")
        elif self.current_task == 'refresh':
            self.task_status_label.setText(dot_gray + "任务状态：刷新中")
            self.task_status_label.setStyleSheet("color: gray;")
        elif self.current_task_id or self.last_task_id:
            try:
                task = self.db.get_task(self.current_task_id or self.last_task_id)
                if task:
                    status_text = {
                        'running': '运行中',
                        'paused': '已暂停',
                        'completed': '已完成',
                        'failed': '失败',
                        'cancelled': '已取消',
                    }.get(task.status, task.status)
                    dot = (dot_blue if task.status == 'running' else
                           dot_orange if task.status == 'paused' else dot_gray)
                    self.task_status_label.setText(dot + f"任务状态：{status_text}")
                    color = 'blue' if task.status == 'running' else (
                        'orange' if task.status == 'paused' else 'gray')
                    self.task_status_label.setStyleSheet(f"color: {color};")
                    return
            except Exception:
                pass
            self.task_status_label.setText(dot_gray + "任务状态：空闲")
            self.task_status_label.setStyleSheet("color: gray;")
        else:
            self.task_status_label.setText(dot_gray + "任务状态：空闲")
            self.task_status_label.setStyleSheet("color: gray;")

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
        """检查子进程状态"""
        try:
            self._update_task_status_label()

            # 任务运行期间每 5 秒做一次浏览器健康检查（方案第 7/30 节）
            self.health_check_ticks += 1
            if self.health_check_ticks % 10 == 0:
                try:
                    mgr = self._get_browser_manager()
                    if (self.current_task == 'download'
                            and self.worker_process and self.worker_process.is_alive()):
                        if not mgr.health_check():
                            self.log("检测到浏览器断开，正在自动恢复...")
                            mgr.reconnect()
                    self._update_browser_status()
                except Exception:
                    pass

            if not self.worker_process:
                self.check_timer.stop()
                self.set_buttons_enabled(True)
                self.start_btn.setVisible(True)
                self.stop_btn.setVisible(False)
                self.pause_btn.setVisible(False)
                self._update_task_status_label()
                return

            if self.worker_process.is_alive():
                # 下载中实时更新进度条（平滑动画）
                if self.current_task == 'download' and self.current_task_id:
                    try:
                        task = self.db.get_task(self.current_task_id)
                        if task and task.total_candidates:
                            self._animate_progress(task.processed_count, task.total_candidates)
                    except Exception:
                        pass
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
                    self.pause_btn.setVisible(False)
                return

            self.check_timer.stop()
            self.progress_bar.setVisible(False)
            self.set_buttons_enabled(True)
            self.start_btn.setVisible(True)
            self.stop_btn.setVisible(False)
            self.pause_btn.setVisible(False)

            if self.result_queue and not self.result_queue.empty():
                result = self.result_queue.get()

                if self.current_task == 'refresh':
                    self._on_refresh_finished(result)
                elif self.current_task == 'download':
                    self._on_download_finished(result)
                    if result.get('paused') or result.get('login_expired'):
                        self.resume_btn.setVisible(True)
                        self.resume_btn.setEnabled(True)
                    else:
                        self.resume_btn.setVisible(False)

            else:
                self.log("任务失败：无结果")

            self.current_task = None
            self.worker_start_time = None
            self._update_task_status_label()
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
            self.pause_btn.setVisible(False)

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
                filtered = sum(1 for c in kept if self.is_school_allowed(c.get('school', '')))
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
        self.candidate_history = {}
        if not candidates:
            return [], {'downloaded': 0, 'ai_rejected': 0}

        try:
            from db.models import generate_candidate_external_id

            def ext_id_of(c):
                return generate_candidate_external_id(
                    c.get('name', ''),
                    c.get('school', '') or '',
                    c.get('major', '') or '',
                )

            ext_ids = [ext_id_of(c) for c in candidates if c.get('name')]
            self.candidate_history = self.db.get_candidates_history(ext_ids)
        except Exception as e:
            print(f"加载候选人历史记录失败: {e}")
            self.candidate_history = {}

        kept = []
        counts = {'downloaded': 0, 'ai_rejected': 0}
        for c in candidates:
            rec = None
            if c.get('name'):
                try:
                    from db.models import generate_candidate_external_id
                    ext_id = generate_candidate_external_id(
                        c.get('name', ''),
                        c.get('school', '') or '',
                        c.get('major', '') or '',
                    )
                    rec = self.candidate_history.get(ext_id)
                except Exception:
                    rec = None
            status = rec.get('status') if rec else None
            if status == 'downloaded':
                counts['downloaded'] += 1
                continue
            if status == 'ai_rejected':
                counts['ai_rejected'] += 1
                continue
            kept.append(c)

        if self.candidate_history:
            self.log(f"{len(self.candidate_history)} 个候选人存在历史处理记录")
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
                self.db.sync_jobs(positions)
            except Exception as e:
                print(f"同步岗位失败: {e}")

        self._run_db_thread(do_sync)
    
    def check_unfinished_tasks(self):
        """检查是否有未完成的任务"""
        if getattr(self, '_unfinished_checked', False):
            return
        self._unfinished_checked = True
        try:
            unfinished = self.db.get_unfinished_tasks()
            if unfinished:
                task = unfinished[0]
                stats = self.db.get_task_stats(task.id)
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
                resume_btn = msg.addButton("继续任务", QMessageBox.ButtonRole.AcceptRole)
                abandon_btn = msg.addButton("放弃任务", QMessageBox.ButtonRole.DestructiveRole)
                msg.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked == resume_btn:
                    self.resume_task(task)
                elif clicked == abandon_btn:
                    self.db.update_task_status(task.id, 'cancelled')
                    self.db.add_task_log(task.id, 'info', '用户放弃任务', event_type='task_paused')
                    self.log(f"已放弃任务 #{task.id}")
        except Exception as e:
            print(f"检查未完成任务失败: {e}")

    def _get_browser_login_status(self):
        """获取 GUI 侧浏览器/登录状态文本（用于恢复任务对话框）"""
        from browser.page_detector import PageDetector, LoginStatus
        from browser.browser_state import STATE_LABELS
        browser_text = '未连接'
        login_text = '未知'
        try:
            mgr = self._get_browser_manager()
            state = mgr.state if mgr else 'DISCONNECTED'
            browser_text = STATE_LABELS.get(state, state)
            page = mgr.get_page() if mgr else None
            if page:
                status = PageDetector.is_logged_in(page=page)
                login_text = {
                    LoginStatus.LOGGED_IN: '正常',
                    LoginStatus.EXPIRED: '已失效',
                    LoginStatus.UNKNOWN: '未知',
                }.get(status, '未知')
        except Exception:
            pass
        return browser_text, login_text

    def _switch_job_in_page(self, page, job_name):
        """在当前页面切换到指定岗位（返回是否成功）"""
        try:
            return page.evaluate('''(targetName) => {
                const items = document.querySelectorAll('.job_name_text');
                for (const el of items) {
                    if (el.textContent.trim() === targetName) {
                        const wrap = el.closest('.job_name_wrap') || el.closest('.menu-item') || el;
                        wrap.click();
                        return true;
                    }
                }
                return false;
            }''', job_name)
        except Exception:
            return False

    def _go_to_page(self, page, page_num):
        """定位到指定页码的候选人列表（方案第 26 节，尽力而为）"""
        if not page or not page_num or page_num <= 1:
            return True
        try:
            return page.evaluate('''(targetPage) => {
                const items = document.querySelectorAll('.eh-pagination__pagelist li');
                for (const el of items) {
                    if (el.textContent.trim() === String(targetPage)) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''', page_num)
        except Exception:
            return False
    
    def resume_task(self, task):
        """恢复任务"""
        try:
            from browser.page_detector import PageDetector, PageType, LoginStatus
            from task import TaskManager

            # 1. 浏览器检查（方案第 23 节）
            mgr = self._get_browser_manager()
            if not mgr.initialize(auto_launch=True):
                self.log(f"浏览器连接失败，无法恢复任务: {mgr.last_error}")
                return
            page = mgr.get_page()
            if not page:
                self.log("未找到浏览器页面，无法恢复任务")
                return

            # 2. 登录状态检查
            login_status = PageDetector.is_logged_in(page=page)
            if login_status == LoginStatus.EXPIRED:
                self.log("前程无忧登录状态已失效，请重新登录后点击“继续任务”")
                self.db.update_task_status(task.id, 'paused')
                self.resume_btn.setVisible(True)
                self.resume_btn.setEnabled(True)
                return

            # 3. 页面类型检查（必须是候选人列表/职位列表页）
            page_type = PageDetector.detect(page=page)
            if page_type not in (PageType.CANDIDATE_LIST_PAGE, PageType.JOB_LIST_PAGE):
                self.log(f"当前页面不是候选人列表页（{page_type}），请先在 Chrome 中打开人才管理页面")
                self.resume_btn.setVisible(True)
                self.resume_btn.setEnabled(True)
                return

            # 4. 岗位匹配检查（方案第 10/35节 场景7）
            current_job = PageDetector.get_current_job(page)
            if current_job and task.job_name and current_job != task.job_name:
                reply = QMessageBox.question(
                    self, "岗位不匹配",
                    f"当前 Chrome 岗位：{current_job}\n"
                    f"任务岗位：{task.job_name}\n\n"
                    "是否切换到任务岗位后继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    self.log("岗位不匹配，任务保持暂停")
                    return
                if not self._switch_job_in_page(page, task.job_name):
                    self.log("切换岗位失败，请手动在 Chrome 中切换后重试")
                    return
                import time as _t
                _t.sleep(5)
                page = mgr.get_page()
                if page and PageDetector.get_current_job(page) != task.job_name:
                    self.log("岗位切换未生效，请手动切换后重试")
                    return

            # 5. 定位任务当前页（方案第 26 节）
            if page and task.current_page and task.current_page > 1:
                self._go_to_page(page, task.current_page)
                import time as _t
                _t.sleep(2)
                page = mgr.get_page()

            # 6. 获取可恢复候选人（pending/processing/failed，跳过已下载/已淘汰）
            tm = TaskManager()
            recoverable = tm.get_recoverable_candidates(task.id)
            if not recoverable:
                self.log(f"任务 #{task.id} 没有待处理的候选人，标记为完成")
                tm.complete_task(task.id)
                self.resume_btn.setVisible(False)
                return

            # 标记任务为运行中
            tm.resume_task(task.id)
            self.current_task_id = task.id
            self.current_task_obj = task

            # 恢复下载配置
            self.job_combo.setCurrentText(task.job_name)
            download_dir = task.download_dir or str(_BASE_DIR / "output" / "resumes")
            self.download_dir_edit.setText(download_dir)

            # 从任务快照恢复 AI 配置（方案第 19 节）
            ai_config = None
            snapshot = tm.db.get_task(task.id)
            restored = tm.restore_ai_snapshot(snapshot.ai_config_snapshot) if snapshot else {}
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

            # 重置中断信号
            self.stop_event.clear()
            self.pause_event.clear()

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

            self.result_queue = multiprocessing.Queue()
            self.worker_process = multiprocessing.Process(
                target=download_worker_target,
                args=(self.result_queue, candidates, download_dir, task.job_name,
                      ai_config, False, self.stop_event, task.id,
                      self.pause_event),
                daemon=True
            )
            self.worker_process.start()
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
                    self._async_update_task_on_complete([], 0, 0, 1, paused=True)
                elif result.get('paused'):
                    self.log(f"任务已暂停: {error}")
                    self._async_update_task_on_complete([], 0, 0, 1, paused=True)
                else:
                    self.log(f"下载失败: {error}")
                    self._async_update_task_on_fail(error)
                return
            results = result.get('results', [])
            success_count = sum(1 for r in results if r.get('success'))
            fail_count = len(results) - success_count
            total_pages = result.get('total_pages', 1)

            self.log(f"下载完成: 成功 {success_count} 个，失败 {fail_count} 个，共 {total_pages} 页")

            # 异步更新数据库任务状态
            paused = self.stop_event.is_set() or self.pause_event.is_set() or result.get('paused', False)
            self.pause_event.clear()
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
                # 累计计数由下载子进程实时写入，这里只更新总页数并置最终状态
                self.db.update_task_progress(task_id, total_pages=total_pages)
                status = 'paused' if paused else 'completed'
                self.db.update_task_status(task_id, status)
                self.db.add_task_log(task_id, 'info', 
                    f'任务{"已暂停" if paused else "完成"}: 成功 {success_count}, 失败 {fail_count}')
            except Exception as e:
                print(f"更新任务状态失败: {e}")
        
        self.last_task_id = task_id
        self.current_task_id = None
        self._run_db_thread(do_update)
    
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
        
        self.last_task_id = task_id
        self.current_task_id = None
        self._run_db_thread(do_update)

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

        self.candidate_table.clearSpans()
        if not display_candidates:
            # 空状态提示
            self.candidate_table.setRowCount(1)
            empty_item = QTableWidgetItem("暂无候选人，请点击“刷新列表”获取")
            empty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_item.setForeground(QColor(148, 163, 184))
            self.candidate_table.setSpan(0, 0, 1, 6)
            self.candidate_table.setItem(0, 0, empty_item)
            return

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

            # 处理记录列（历史下载结果/失败原因）
            record = self._candidate_history_for(candidate)
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
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.candidate_table.setCellWidget(i, 5, badge)
            else:
                self.candidate_table.setItem(i, 5, QTableWidgetItem(''))

    def _candidate_history_for(self, candidate):
        """返回候选人的历史处理记录展示信息（文本/悬浮提示/颜色）"""
        try:
            from db.models import generate_candidate_external_id
            ext_id = generate_candidate_external_id(
                candidate.get('name', ''),
                candidate.get('school', '') or '',
                candidate.get('major', '') or '',
            )
        except Exception:
            ext_id = ''

        rec = self.candidate_history.get(ext_id)
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

        tooltip = f"岗位: {job}\n状态: {detail}\n时间: {ts}"
        return {'text': text, 'tooltip': tooltip, 'color': color}

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
            self._update_ai_status()
            self.log("AI 配置已保存")

    def show_about(self):
        QMessageBox.about(self, "关于",
            "AI 简历批量初筛与下载助手\n\n"
            "基于Python + Playwright的浏览器自动化工具\n"
            "用于从前程无忧自动下载候选人简历\n"
            "支持AI简历筛选和学校名单过滤\n\n"
            "版本: 1.1.0")

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

        # 等待数据库后台线程结束（防止退出时 QThread 仍在运行导致 abort）
        for thread in list(self._db_threads):
            try:
                thread.wait(timeout=3000)
            except Exception:
                pass
        event.accept()


class AIConfigDialog(QDialog):
    """AI配置对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI简历筛选配置")
        self.setMinimumWidth(640)
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
        self.api_key_edit.setPlaceholderText("输入 MiMo API Key")
        api_layout.addWidget(self.api_key_edit, 0, 1, 1, 2)

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_connection)
        api_layout.addWidget(self.test_btn, 1, 1)
        self.test_result_label = QLabel("")
        self.test_result_label.setWordWrap(True)
        api_layout.addWidget(self.test_result_label, 1, 2)

        api_layout.addWidget(QLabel("启用AI筛选:"), 2, 0)
        self.enabled_check = QCheckBox()
        api_layout.addWidget(self.enabled_check, 2, 1)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        desc_group = QGroupBox("岗位匹配描述")
        desc_layout = QVBoxLayout()

        self.desc_table = QTableWidget()
        self.desc_table.setColumnCount(2)
        self.desc_table.setHorizontalHeaderLabels(["岗位名称", "匹配描述"])
        self.desc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.desc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # 行高足够容纳输入框（QSS padding 7px 会把行内输入框压扁、文字不可见）
        self.desc_table.verticalHeader().setVisible(False)
        self.desc_table.verticalHeader().setDefaultSectionSize(40)
        self.desc_table.setShowGrid(False)
        desc_layout.addWidget(self.desc_table)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加")
        self.add_btn.clicked.connect(self.add_description)
        self.remove_btn = QPushButton("删除选中")
        self.remove_btn.clicked.connect(self.remove_description)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        desc_layout.addLayout(btn_layout)

        desc_group.setLayout(desc_layout)
        layout.addWidget(desc_group)

        # AI 描述生成器
        gen_group = QGroupBox("AI 生成专业匹配描述")
        gen_layout = QVBoxLayout()
        gen_layout.addWidget(QLabel(
            "输入原始要求（用逗号分隔），点击生成后自动填入选中行的描述："
        ))
        self.gen_input = QLineEdit()
        self.gen_input.setPlaceholderText("例如：2年react, 4年经验, 本科以上, 有全栈经验")
        gen_layout.addWidget(self.gen_input)
        gen_btn_row = QHBoxLayout()
        self.gen_btn = QPushButton("生成专业描述")
        self.gen_btn.clicked.connect(self.generate_description)
        self.gen_result_label = QLabel("")
        self.gen_result_label.setWordWrap(True)
        gen_btn_row.addWidget(self.gen_btn)
        gen_btn_row.addWidget(self.gen_result_label, 1)
        gen_layout.addLayout(gen_btn_row)
        gen_group.setLayout(gen_layout)
        layout.addWidget(gen_group)

        button_layout = QHBoxLayout()
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

    def load_config(self):
        self.api_key_edit.setText(self.config.get("api_key", ""))
        self.enabled_check.setChecked(self.config.get("enabled", False))
        job_descs = self.config.get("job_descriptions", {})
        self.desc_table.setRowCount(0)
        for i, (name, desc) in enumerate(job_descs.items()):
            self._add_row(name, desc)
        if self.desc_table.rowCount() == 0:
            self._add_row("", "")

    def _add_row(self, name="", desc=""):
        """添加一行：岗位名 + 描述（用真实 QLineEdit，文本始终可见）"""
        row = self.desc_table.rowCount()
        self.desc_table.insertRow(row)
        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("岗位名称，如：前端开发工程师")
        desc_edit = QLineEdit(desc)
        desc_edit.setPlaceholderText("输入匹配描述，如：2年react, 4年经验, 本科以上")
        self.desc_table.setCellWidget(row, 0, name_edit)
        self.desc_table.setCellWidget(row, 1, desc_edit)
        return row

    def save_config(self):
        self.config["api_key"] = self.api_key_edit.text()
        self.config["enabled"] = self.enabled_check.isChecked()
        job_descs = {}
        for i in range(self.desc_table.rowCount()):
            name_w = self.desc_table.cellWidget(i, 0)
            desc_w = self.desc_table.cellWidget(i, 1)
            if not name_w or not desc_w:
                continue
            name = name_w.text().strip()
            desc = desc_w.text().strip()
            if name and desc:
                job_descs[name] = desc
        self.config["job_descriptions"] = job_descs
        save_ai_config(self.config)

    def add_description(self):
        row = self._add_row()
        self.desc_table.selectRow(row)
        self.desc_table.scrollToBottom()

    def remove_description(self):
        current_row = self.desc_table.currentRow()
        if current_row >= 0:
            self.desc_table.removeRow(current_row)

    def _call_llm(self, api_key, messages, max_tokens=50, temperature=0.1):
        """调用 MiMo API（测试连接/生成描述共用）"""
        from openai import OpenAI
        from config import MIMO_API_BASE, MIMO_MODEL
        client = OpenAI(api_key=api_key, base_url=MIMO_API_BASE)
        completion = client.chat.completions.create(
            model=MIMO_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (completion.choices[0].message.content or "").strip()

    def test_connection(self):
        """测试 API Key 是否可用"""
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            self.test_result_label.setText("请先输入 API Key")
            self.test_result_label.setStyleSheet("color: #D97706;")
            return
        self.test_btn.setEnabled(False)
        self.test_result_label.setText("测试中...")
        self.test_result_label.setStyleSheet("color: #2563EB;")
        try:
            text = self._call_llm(
                api_key,
                [{"role": "user", "content": "只回复两个字：正常"}],
                max_tokens=10,
                temperature=0,
            )
            self.test_result_label.setText(f"连接成功 ✓（{text[:20]}）")
            self.test_result_label.setStyleSheet("color: #16A34A;")
        except Exception as e:
            self.test_result_label.setText(f"连接失败: {e}")
            self.test_result_label.setStyleSheet("color: #DC2626;")
        finally:
            self.test_btn.setEnabled(True)

    def generate_description(self):
        """根据原始要求调用 AI 生成专业匹配描述，直接新增一行"""
        raw = self.gen_input.text().strip()
        api_key = self.api_key_edit.text().strip()
        if not raw:
            self.gen_result_label.setText("请先输入原始要求")
            self.gen_result_label.setStyleSheet("color: #D97706;")
            return
        if not api_key:
            self.gen_result_label.setText("请先输入 API Key")
            self.gen_result_label.setStyleSheet("color: #D97706;")
            return
        self.gen_btn.setEnabled(False)
        self.gen_result_label.setText("生成中...")
        self.gen_result_label.setStyleSheet("color: #2563EB;")
        try:
            prompt = (
                "你是资深招聘HR。请根据以下原始岗位要求，生成一段专业、结构清晰、便于AI筛选简历的岗位匹配描述。"
                "覆盖工作年限、技能栈、学历、核心能力等，用中文简洁分点表达，"
                "直接输出描述内容，不要多余解释。\n\n原始要求：\n" + raw
            )
            text = self._call_llm(
                api_key,
                [
                    {"role": "system", "content": "你是简历筛选专家，只输出岗位匹配描述本身。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=400,
                temperature=0.3,
            )
            # 新增一条匹配描述（岗位名预填当前岗位，便于直接使用）
            job_name = ""
            if self.parent() and hasattr(self.parent(), "current_job"):
                job_name = self.parent().current_job or ""
            row = self._add_row(job_name, text)
            self.desc_table.selectRow(row)
            self.desc_table.scrollToBottom()
            self.gen_result_label.setText("已生成并新增一条匹配描述 ✓")
            self.gen_result_label.setStyleSheet("color: #16A34A;")
        except Exception as e:
            self.gen_result_label.setText(f"生成失败: {e}")
            self.gen_result_label.setStyleSheet("color: #DC2626;")
        finally:
            self.gen_btn.setEnabled(True)

    def accept(self):
        self.save_config()
        super().accept()
