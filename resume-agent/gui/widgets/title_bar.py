# -*- coding: utf-8 -*-
from gui.qt_compat import LeftButton, NoFocus, PointingHandCursor, WindowMaximized
"""
自定义标题栏（无边框窗口用）

支持：
- 左键拖拽移动窗口
- 双击标题栏最大化/还原
- 最小化 / 最大化/还原 / 关闭 按钮（使用 Windows 自带 Segoe MDL2 Assets 图标）
"""
from gui.qt_compat import Qt
from gui.qt_compat import QHBoxLayout, QLabel, QToolButton, QWidget


class TitleBar(QWidget):
    """现代风格标题栏"""

    HEIGHT = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(self.HEIGHT)
        self._drag_offset = None
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(4)

        # 应用名
        self.title_label = QLabel("林林专属助手")
        self.title_label.setObjectName("titleLabel")
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        # 窗口控制按钮
        self.min_btn = self._make_control_btn("\uE921", "minBtn", "最小化")
        self.max_btn = self._make_control_btn("\uE922", "maxBtn", "最大化")
        self.close_btn = self._make_control_btn("\uE8BB", "closeBtn", "关闭")

        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

        self.min_btn.clicked.connect(lambda: self.window().showMinimized())
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn.clicked.connect(lambda: self.window().close())

    def _make_control_btn(self, glyph, obj_name, tip):
        btn = QToolButton()
        btn.setObjectName(obj_name)
        btn.setText(glyph)
        btn.setToolTip(tip)
        btn.setFixedSize(46, self.HEIGHT)
        btn.setFont(self._mdl2_font())
        btn.setCursor(PointingHandCursor)
        btn.setFocusPolicy(NoFocus)
        return btn

    @staticmethod
    def _mdl2_font():
        from gui.qt_compat import QFont
        font = QFont("Segoe MDL2 Assets")
        font.setPixelSize(12)
        return font

    def _toggle_maximize(self):
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()
        self._update_max_icon(win.isMaximized())

    def _update_max_icon(self, maximized):
        if maximized:
            self.max_btn.setText("\uE923")  # 还原
            self.max_btn.setToolTip("还原")
        else:
            self.max_btn.setText("\uE922")  # 最大化
            self.max_btn.setToolTip("最大化")

    def on_window_state_changed(self, state):
        self._update_max_icon(bool(state & WindowMaximized))

    # ==================== 拖拽 ====================

    def mousePressEvent(self, event):
        if event.button() == LeftButton:
            win = self.window()
            if not win.isMaximized():
                self._drag_offset = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & LeftButton:
            win = self.window()
            if not win.isMaximized():
                win.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)
