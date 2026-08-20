# -*- coding: utf-8 -*-
"""
浏览器后台监控线程（问题6/7）

- 在独立线程中持有自己的 BrowserManager，周期健康检查，不阻塞 GUI 主线程；
- 空闲时浏览器断开会自动后台重连；
- 下载/刷新 worker 运行期间关闭自动重连（恢复交给 worker 自己处理），
  但状态仍持续上报，界面标签不会因为浏览器断开而失去反馈。
"""
import time

from gui.qt_compat import QThread, pyqtSignal


class BrowserMonitorThread(QThread):
    """浏览器状态监控线程"""

    status_changed = pyqtSignal(str)   # BrowserState 字符串
    log_message = pyqtSignal(str)

    CHECK_INTERVAL = 5.0

    def __init__(self, port=9222, parent=None):
        super().__init__(parent)
        self._port = port
        self._stop = False
        self._reconnect_allowed = True
        self._manager = None

    def set_reconnect_allowed(self, allowed: bool):
        """是否允许本线程自动重连（任务运行期间关闭，避免与 worker 抢 Chrome）"""
        self._reconnect_allowed = allowed

    def stop_monitor(self):
        self._stop = True

    def run(self):
        try:
            from browser.browser_manager import BrowserManager
            from browser.browser_state import BrowserState
        except Exception as e:
            self.log_message.emit(f"浏览器监控初始化失败: {e}")
            return

        self._manager = BrowserManager(port=self._port)
        self._state = BrowserState.DISCONNECTED
        self.status_changed.emit(self._state)

        while not self._stop:
            self._tick()
            # 分段等待，保证 stop_monitor 能及时生效
            for _ in range(10):
                if self._stop:
                    return
                time.sleep(self.CHECK_INTERVAL / 10)

    def _tick(self):
        try:
            if self._manager is None:
                return
            if self._manager.health_check():
                self._report('READY')
                return
            if not self._reconnect_allowed:
                self._report('DISCONNECTED')
                return
            self._report('RECONNECTING', '检测到浏览器断开，正在后台自动恢复...')
            if self._manager.reconnect():
                self._report('READY', '浏览器已重新连接')
            else:
                self._report('ERROR', f'浏览器自动重连失败: {self._manager.last_error or ""}')
        except Exception as e:
            self._report('ERROR', f'浏览器监控异常: {e}')

    def _report(self, state, msg=''):
        if state != getattr(self, '_state', None):
            self._state = state
            self.status_changed.emit(state)
        if msg:
            self.log_message.emit(msg)
