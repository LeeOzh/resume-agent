# -*- coding: utf-8 -*-
"""
浏览器状态（改造方案第 6 节）

DISCONNECTED -> STARTING -> CONNECTING -> CONNECTED -> READY
异常：READY -> RECONNECTING -> CONNECTED -> READY
"""


class BrowserState:
    DISCONNECTED = 'DISCONNECTED'
    STARTING = 'STARTING'
    CONNECTING = 'CONNECTING'
    CONNECTED = 'CONNECTED'
    READY = 'READY'
    RECONNECTING = 'RECONNECTING'
    ERROR = 'ERROR'


# UI 展示映射
STATE_LABELS = {
    BrowserState.DISCONNECTED: '浏览器：未连接',
    BrowserState.STARTING: '浏览器：连接中',
    BrowserState.CONNECTING: '浏览器：连接中',
    BrowserState.CONNECTED: '浏览器：已连接',
    BrowserState.READY: '浏览器：已连接',
    BrowserState.RECONNECTING: '浏览器：重连中',
    BrowserState.ERROR: '浏览器：异常',
}
