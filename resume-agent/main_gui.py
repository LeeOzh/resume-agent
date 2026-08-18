# -*- coding: utf-8 -*-
"""
AI 简历批量初筛与下载助手 - GUI版本
"""
import sys
import os
import traceback
from pathlib import Path

# 设置基础目录
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

# 写入日志文件以便调试
LOG_FILE = BASE_DIR / "startup.log"


def log_to_file(msg):
    """写入日志文件"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now()}] {msg}\n")
    except Exception:
        pass


def show_error(title, message):
    """显示错误对话框"""
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, title, message)
    except Exception:
        print(f"\n{title}\n{message}")


def main():
    """主函数"""
    log_to_file("=== 启动开始 ===")
    
    try:
        log_to_file("导入PyQt5...")
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        log_to_file("PyQt5导入成功")
        
        log_to_file("导入MainWindow...")
        from gui.main_window import MainWindow
        log_to_file("MainWindow导入成功")

        # 设置高DPI支持（PyQt5）
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        
        log_to_file("创建QApplication...")
        app = QApplication(sys.argv)
        
        # 设置应用程序信息
        app.setApplicationName("AI 简历批量初筛与下载助手")
        app.setApplicationVersion("1.1.0")
        app.setOrganizationName("ResumeAgent")
        
        log_to_file("创建MainWindow...")
        window = MainWindow()
        log_to_file("MainWindow创建成功")
        
        log_to_file("显示窗口...")
        window.show()
        log_to_file("窗口显示成功")
        
        # 运行应用程序
        log_to_file("进入事件循环...")
        sys.exit(app.exec())
        
    except Exception as e:
        error_msg = f"启动失败: {str(e)}\n\n{traceback.format_exc()}"
        log_to_file(error_msg)
        print(error_msg)
        show_error("启动错误", error_msg)
        sys.exit(1)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
