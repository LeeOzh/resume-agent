# -*- coding: utf-8 -*-
"""
Qt 绑定兼容层：统一 PyQt6 / PyQt5 的 import 与枚举差异。

设计约定：
- 绑定选择以 QT_BINDING 环境变量为主（pyqt6 / pyqt5），未设置时自动探测（优先 PyQt6）
- 本模块只负责"统一 Qt API 差异"，不承担 Fluent Widgets 业务、GUI 组件封装、页面业务
- 业务代码禁止出现 if PYQT5/if QT_VERSION 判断，一律使用本模块导出的统一 API
"""
import os


QT_BINDING = os.getenv("QT_BINDING", "").strip().lower()
if not QT_BINDING:
    # fallback：自动探测已安装的 Qt（优先 PyQt6）
    try:
        import PyQt6  # noqa: F401
        QT_BINDING = "pyqt6"
    except ImportError:
        try:
            import PyQt5  # noqa: F401
            QT_BINDING = "pyqt5"
        except ImportError:
            raise RuntimeError("未安装 PyQt5 或 PyQt6")


if QT_BINDING == "pyqt6":
    from PyQt6.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    )
    from PyQt6.QtGui import (
        QAction, QShortcut, QColor, QFont, QKeySequence,
    )
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
        QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
        QSplitter, QStackedWidget, QStatusBar, QTableWidget, QTableWidgetItem,
        QTextEdit, QToolButton, QVBoxLayout, QWidget,
    )

    QT_VERSION = 6
    IS_QT6 = True
    IS_QT5 = False

    AlignCenter = Qt.AlignmentFlag.AlignCenter
    PointingHandCursor = Qt.CursorShape.PointingHandCursor
    NoFocus = Qt.FocusPolicy.NoFocus
    UserRole = Qt.ItemDataRole.UserRole
    LeftButton = Qt.MouseButton.LeftButton
    Horizontal = Qt.Orientation.Horizontal
    ScrollBarAlwaysOff = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    TextSelectableByMouse = Qt.TextInteractionFlag.TextSelectableByMouse
    WindowMaximized = Qt.WindowState.WindowMaximized
    HeaderStretch = QHeaderView.ResizeMode.Stretch
    MessageBoxYes = QMessageBox.StandardButton.Yes
    MessageBoxNo = QMessageBox.StandardButton.No
    AcceptRole = QMessageBox.ButtonRole.AcceptRole
    DestructiveRole = QMessageBox.ButtonRole.DestructiveRole
    RejectRole = QMessageBox.ButtonRole.RejectRole
    DialogAccepted = QDialog.DialogCode.Accepted
    DialogRejected = QDialog.DialogCode.Rejected

elif QT_BINDING == "pyqt5":
    from PyQt5.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    )
    from PyQt5.QtGui import (
        QColor, QFont, QKeySequence,
    )
    from PyQt5.QtWidgets import (
        QApplication, QAction, QShortcut, QDialog, QFileDialog, QFrame,
        QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
        QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
        QPushButton, QScrollArea, QSplitter, QStackedWidget, QStatusBar,
        QTableWidget, QTableWidgetItem, QTextEdit, QToolButton, QVBoxLayout,
        QWidget,
    )

    QT_VERSION = 5
    IS_QT6 = False
    IS_QT5 = True

    AlignCenter = Qt.AlignCenter
    PointingHandCursor = Qt.PointingHandCursor
    NoFocus = Qt.NoFocus
    UserRole = Qt.UserRole
    LeftButton = Qt.LeftButton
    Horizontal = Qt.Horizontal
    ScrollBarAlwaysOff = Qt.ScrollBarAlwaysOff
    TextSelectableByMouse = Qt.TextSelectableByMouse
    WindowMaximized = Qt.WindowMaximized
    HeaderStretch = QHeaderView.Stretch
    MessageBoxYes = QMessageBox.Yes
    MessageBoxNo = QMessageBox.No
    AcceptRole = QMessageBox.AcceptRole
    DestructiveRole = QMessageBox.DestructiveRole
    RejectRole = QMessageBox.RejectRole
    DialogAccepted = QDialog.Accepted
    DialogRejected = QDialog.Rejected

else:
    raise RuntimeError(f"Unsupported QT_BINDING: {QT_BINDING}")


def enable_high_dpi():
    """启用高 DPI 支持（在创建 QApplication 之前调用）"""
    if QT_VERSION == 6:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    else:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)


def exec_app(app):
    """统一进入事件循环（屏蔽 PyQt5 exec_ / PyQt6 exec 差异）"""
    return app.exec()
