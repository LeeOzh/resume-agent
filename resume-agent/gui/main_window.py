# -*- coding: utf-8 -*-
from gui.qt_compat import HeaderStretch
"""
主窗口模块 - 林林专属助手

窗口结构：
    ResumeAgent
    ├── 简历自动化（AutomationPage，原 MainWindow 业务逻辑整体迁移）
    └── 微信简历（WeChatPage，微信群简历监听）

本文件只保留窗口级内容：Fluent 导航、状态栏、主题、AI 配置对话框、
浏览器后台监控线程与退出清理；业务逻辑见 gui/pages/。
"""
import sys
import os
from pathlib import Path

from gui.qt_compat import (
QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
QDialog, QMessageBox, QStatusBar, QGroupBox, QGridLayout, QLineEdit,
DialogAccepted,
QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget,
)
from gui.qt_compat import Qt, QTimer
from gui.qt_compat import QAction, QShortcut, QKeySequence
from qfluentwidgets import (
    FluentIcon, PrimaryPushButton, PushButton, ComboBox, TableWidget,
    CheckBox as FluentCheckBox, LineEdit as FluentLineEdit,
    InfoBadge, InfoLevel, IndeterminateProgressBar,
    NavigationInterface, NavigationItemPosition,
    setTheme, Theme, setThemeColor,
)

from config import load_ai_config, save_ai_config
from db import Database


# 获取基础目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent


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


class MainWindow(QMainWindow):
    """主窗口：Fluent 导航容器（ResumeAgent -> 简历自动化 / 微信简历）"""

    def __init__(self):
        super().__init__()

        # 数据库（页面共享同一实例）
        self.db = Database()

        self.setWindowTitle("林林专属助手")
        # 原生窗口边框：自由缩放由系统支持；这里只保留一个合理下限避免布局崩坏
        self.setMinimumSize(860, 600)
        self.theme = 'light'

        self.apply_theme('light')

        # 浏览器后台监控线程：周期健康检查，断开时后台自动重连，不阻塞界面
        # （先创建，页面构造时会持有该引用）
        from gui.threads.browser_monitor import BrowserMonitorThread
        self.browser_monitor = BrowserMonitorThread(parent=self)

        self.setup_navigation()

        # 连接浏览器监控信号
        self.browser_monitor.status_changed.connect(self.automation_page._on_monitor_status)
        self.browser_monitor.log_message.connect(
            lambda msg: self.automation_page.log(f"[浏览器] {msg}")
        )
        self.browser_monitor.start()
        # 开发/截图模式（RA_NO_AUTO_REFRESH=1）下只报告状态，不自动拉起 Chrome
        if os.environ.get("RA_NO_AUTO_REFRESH") == "1":
            self.browser_monitor.set_reconnect_allowed(False)

        # 快捷键（F5 刷新 / Ctrl+Enter 开始下载）
        QShortcut(QKeySequence("F5"), self, activated=self.automation_page.refresh_candidates)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.automation_page.start_download)

        # 启动后自动检查 Chrome / 未完成任务
        self.automation_page.start_auto()

        # 根据已保存的 AI 配置刷新状态显示（否则重启后一直显示“未配置”）
        self._update_ai_status()

    # ---------------- 导航/布局 ----------------

    def setup_navigation(self):
        # 根窗口：容器铺满，无外层边距
        root_widget = QWidget()
        self._root_layout = QVBoxLayout(root_widget)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(root_widget)

        # 容器：顶部栏 + 主体 + 状态栏（使用原生窗口边框）
        self.window_container = QWidget()
        self.window_container.setObjectName("windowContainer")
        self._container_layout = QVBoxLayout(self.window_container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)
        self._root_layout.addWidget(self.window_container)

        # 顶部栏：标题 + 操作按钮
        header_widget = QWidget()
        self._header_layout = QHBoxLayout(header_widget)
        self._header_layout.setContentsMargins(16, 10, 16, 6)
        self._header_layout.setSpacing(8)
        title_label = QLabel("林林专属助手")
        title_label.setObjectName("appTitleLabel")
        self._header_layout.addWidget(title_label)
        self._header_layout.addStretch()
        self._container_layout.addWidget(header_widget)

        self.setup_menu()
        self.setup_toolbar()

        # 主体：左侧 Fluent 导航 + 右侧页面堆栈
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.navigation = NavigationInterface(
            body, showMenuButton=True, showReturnButton=False, collapsible=True
        )
        self.navigation.setExpandWidth(230)
        body_layout.addWidget(self.navigation)

        self._stack = QStackedWidget(body)
        body_layout.addWidget(self._stack, 1)
        self._container_layout.addWidget(body, 1)

        # 状态栏（页面构造需要状态栏标签引用，因此放在页面创建前）
        self.setup_statusbar()

        # 页面
        from gui.pages.automation_page import AutomationPage
        from gui.pages.wechat_page import WeChatPage
        self.automation_page = AutomationPage(self)
        self.wechat_page = WeChatPage(self)
        self._stack.addWidget(self.automation_page)
        self._stack.addWidget(self.wechat_page)

        # 顶部刷新按钮指向自动化页
        self.toolbar_refresh_btn.clicked.connect(
            lambda: self.automation_page.refresh_candidates()
        )

        # 导航条目：平铺 简历自动化 / 微信简历
        self.navigation.addItem(
            routeKey='automation',
            icon=FluentIcon.ROBOT,
            text='简历自动化',
            onClick=lambda: self._switch_page(0),
        )
        self.navigation.addItem(
            routeKey='wechat',
            icon=FluentIcon.CHAT,
            text='微信简历',
            onClick=lambda: self._switch_page(1),
        )
        self.navigation.setCurrentItem(self.navigation.widget('automation'))
        self._switch_page(0)

    def _switch_page(self, index):
        """切换页面堆栈"""
        self._stack.setCurrentIndex(index)

    # ---------------- 主题 ----------------

    def apply_theme(self, theme='light'):
        """应用主题样式（light / dark）"""
        self.theme = theme
        try:
            # Fluent 组件主题（qfluentwidgets）
            setTheme(Theme.DARK if theme == 'dark' else Theme.LIGHT)
            setThemeColor("#2563EB")
        except Exception:
            pass
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

    def setup_menu(self):
        """Fluent 头部操作按钮（替代菜单栏），业务动作不变"""
        self.dark_theme_action = QAction("暗色主题", self)
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.setChecked(self.theme == 'dark')
        self.dark_theme_action.toggled.connect(
            lambda checked: self.apply_theme('dark' if checked else 'light')
        )

        self.header_ai_btn = PushButton("AI配置")
        self.header_ai_btn.clicked.connect(self.show_ai_config)
        self.header_theme_btn = PushButton("暗色" if self.theme == 'light' else "亮色")
        self.header_theme_btn.clicked.connect(self.toggle_theme_btn)
        self.header_about_btn = PushButton("关于")
        self.header_about_btn.clicked.connect(self.show_about)

        self._header_layout.addWidget(self.header_ai_btn)
        self._header_layout.addWidget(self.header_theme_btn)
        self._header_layout.addWidget(self.header_about_btn)

    def toggle_theme_btn(self):
        """头部主题按钮：亮/暗切换"""
        self.apply_theme('dark' if self.theme == 'light' else 'light')
        self.header_theme_btn.setText("亮色" if self.theme == 'dark' else "暗色")

    def setup_toolbar(self):
        """头部刷新按钮（替代工具栏）"""
        self.toolbar_refresh_btn = PrimaryPushButton("刷新")
        self.toolbar_refresh_btn.setIcon(FluentIcon.SYNC)
        self._header_layout.addWidget(self.toolbar_refresh_btn)

    # ---------------- 状态栏 ----------------

    def setup_statusbar(self):
        # 状态栏放入容器内
        self._statusbar = QStatusBar(self.window_container)
        self._statusbar.setObjectName("appStatusBar")
        self._statusbar.showMessage("就绪")

        self.candidate_count_label = QLabel("候选人: 0")
        self.download_count_label = QLabel("已下载: 0")
        self.ai_status_label = InfoBadge("AI: 未配置", None, InfoLevel.INFOAMTION)
        self.browser_status_label = InfoBadge("浏览器：未连接", None, InfoLevel.INFOAMTION)
        self.task_status_label = InfoBadge("任务状态：空闲", None, InfoLevel.INFOAMTION)

        self._statusbar.addPermanentWidget(self.candidate_count_label)
        self._statusbar.addPermanentWidget(self.download_count_label)
        self._statusbar.addPermanentWidget(self.ai_status_label)
        self._statusbar.addPermanentWidget(self.browser_status_label)
        self._statusbar.addPermanentWidget(self.task_status_label)
        self._container_layout.addWidget(self._statusbar)

    # ---------------- AI 配置 ----------------

    def _update_ai_status(self):
        """根据已保存的 AI 配置刷新状态栏显示与自动化页"""
        config = load_ai_config()
        has_key = bool(config.get("api_key"))
        enabled = bool(config.get("enabled")) and has_key
        if enabled:
            self.ai_status_label.setText("AI: 已启用")
            self.ai_status_label.setLevel(InfoLevel.SUCCESS)
        else:
            reason = "未配置" if not has_key else "未启用"
            self.ai_status_label.setText(f"AI: {reason}")
            self.ai_status_label.setLevel(InfoLevel.INFOAMTION)
        if hasattr(self, 'automation_page'):
            self.automation_page.refresh_ai_status()

    def show_ai_config(self):
        dialog = AIConfigDialog(self.automation_page)
        if dialog.exec() == DialogAccepted:
            self._update_ai_status()
            self.automation_page.log("AI 配置已保存")

    def show_about(self):
        QMessageBox.about(self, "关于",
            "林林专属助手\n\n"
            "基于Python + Playwright的浏览器自动化工具\n"
            "用于从前程无忧自动下载候选人简历\n"
            "支持AI简历筛选和学校名单过滤\n"
            "新增：微信群简历监听（pyweixin，微信 4.1）\n\n"
            "版本: 1.2.0")

    # ---------------- 退出 ----------------

    def closeEvent(self, event):
        # 自动化页：任务运行中询问用户，等待 DB 线程结束
        if hasattr(self, 'automation_page') and self.automation_page:
            if not self.automation_page.shutdown():
                event.ignore()
                return
        # 微信监听页：停止监听线程
        if hasattr(self, 'wechat_page') and self.wechat_page:
            self.wechat_page.shutdown()
        # 停止浏览器后台监控线程
        if self.browser_monitor is not None:
            self.browser_monitor.stop_monitor()
            self.browser_monitor.wait(2000)
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
        self.api_key_edit = FluentLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("输入 MiMo API Key")
        api_layout.addWidget(self.api_key_edit, 0, 1, 1, 2)

        self.test_btn = PushButton("测试连接")
        self.test_btn.clicked.connect(self.test_connection)
        api_layout.addWidget(self.test_btn, 1, 1)
        self.test_result_label = QLabel("")
        self.test_result_label.setWordWrap(True)
        api_layout.addWidget(self.test_result_label, 1, 2)

        api_layout.addWidget(QLabel("启用AI筛选:"), 2, 0)
        self.enabled_check = FluentCheckBox()
        api_layout.addWidget(self.enabled_check, 2, 1)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        desc_group = QGroupBox("岗位匹配描述")
        desc_layout = QVBoxLayout()

        self.desc_table = TableWidget()
        self.desc_table.setColumnCount(2)
        self.desc_table.setHorizontalHeaderLabels(["岗位名称", "匹配描述"])
        self.desc_table.horizontalHeader().setSectionResizeMode(1, HeaderStretch)
        self.desc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # 行高足够容纳输入框（QSS padding 7px 会把行内输入框压扁、文字不可见）
        self.desc_table.verticalHeader().setVisible(False)
        self.desc_table.verticalHeader().setDefaultSectionSize(40)
        self.desc_table.setShowGrid(False)
        desc_layout.addWidget(self.desc_table)

        btn_layout = QHBoxLayout()
        self.add_btn = PushButton("添加")
        self.add_btn.clicked.connect(self.add_description)
        self.remove_btn = PushButton("删除选中")
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
        self.gen_input = FluentLineEdit()
        self.gen_input.setPlaceholderText("例如：2年react, 4年经验, 本科以上, 有全栈经验")
        gen_layout.addWidget(self.gen_input)
        gen_btn_row = QHBoxLayout()
        self.gen_btn = PrimaryPushButton("生成专业描述")
        self.gen_btn.clicked.connect(self.generate_description)
        self.gen_result_label = QLabel("")
        self.gen_result_label.setWordWrap(True)
        gen_btn_row.addWidget(self.gen_btn)
        gen_btn_row.addWidget(self.gen_result_label, 1)
        gen_layout.addLayout(gen_btn_row)
        gen_group.setLayout(gen_layout)
        layout.addWidget(gen_group)

        # 加载指示条（测试连接/生成描述时显示）
        self.loading_bar = IndeterminateProgressBar(self)
        self.loading_bar.setFixedHeight(3)
        self.loading_bar.setVisible(False)
        layout.addWidget(self.loading_bar)

        button_layout = QHBoxLayout()
        self.ok_btn = PrimaryPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = PushButton("取消")
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
        name_edit = FluentLineEdit()
        name_edit.setText(name)
        name_edit.setPlaceholderText("岗位名称，如：前端开发工程师")
        desc_edit = FluentLineEdit()
        desc_edit.setText(desc)
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
        self.gen_btn.setEnabled(False)
        self.test_result_label.setText("测试中...")
        self.test_result_label.setStyleSheet("color: #2563EB;")
        self.loading_bar.setVisible(True)
        self.loading_bar.start()
        try:
            text = self._call_llm(
                api_key,
                [{"role": "user", "content": "只回复两个字：正常"}],
                max_tokens=100,
                temperature=0,
            )
            tip = f"（{text[:20]}）" if text else "（API 已响应）"
            self.test_result_label.setText(f"连接成功 ✓{tip}")
            self.test_result_label.setStyleSheet("color: #16A34A;")
        except Exception as e:
            self.test_result_label.setText(f"连接失败: {e}")
            self.test_result_label.setStyleSheet("color: #DC2626;")
        finally:
            self.test_btn.setEnabled(True)
            self.gen_btn.setEnabled(True)
            self.loading_bar.stop()
            self.loading_bar.setVisible(False)

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
        self.test_btn.setEnabled(False)
        self.gen_result_label.setText("生成中...")
        self.gen_result_label.setStyleSheet("color: #2563EB;")
        self.loading_bar.setVisible(True)
        self.loading_bar.start()
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
                max_tokens=2000,
                temperature=0.3,
            )
            if not text:
                self.gen_result_label.setText("模型未返回内容（推理过长），请重试")
                self.gen_result_label.setStyleSheet("color: #DC2626;")
                return
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
            self.test_btn.setEnabled(True)
            self.loading_bar.stop()
            self.loading_bar.setVisible(False)

    def accept(self):
        self.save_config()
        super().accept()
