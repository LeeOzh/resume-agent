# -*- mode: python ; coding: utf-8 -*-
"""PyQt5 兼容版打包（onedir，面向 Win7 / Win10 1511 等旧系统）。"""
from PyInstaller.utils.hooks import collect_all

block_cipher = None

openai_datas, openai_binaries, openai_hiddenimports = collect_all('openai')
pyqt_datas, pyqt_binaries, pyqt_hiddenimports = collect_all('PyQt5')
fluent_datas, fluent_binaries, fluent_hiddenimports = collect_all('qfluentwidgets')

_wechat_pkgs = [
    'pywechat', 'pyweixin', 'pywinauto', 'pyautogui', 'comtypes',
    'pywin32', 'pycaw', 'sounddevice', 'soundfile', 'emoji',
    'packaging', 'psutil', 'pyscreeze', 'pymsgbox', 'pygetwindow',
    'mouseinfo', 'pyperclip', 'pyrect', 'pytweening',
]
_wechat_datas, _wechat_binaries, _wechat_hiddenimports = [], [], []
for _pkg in _wechat_pkgs:
    try:
        _d, _b, _h = collect_all(_pkg)
        _wechat_datas += _d
        _wechat_binaries += _b
        _wechat_hiddenimports += _h
    except Exception:
        pass

a = Analysis(
    ['main_gui.py'],
    pathex=[],
    binaries=(openai_binaries + pyqt_binaries + fluent_binaries + _wechat_binaries),
    datas=(openai_datas + pyqt_datas + fluent_datas + _wechat_datas + [
        ('gui/resources/styles/*.qss', 'gui/resources/styles'),
        ('gui/resources/icons/*.svg', 'gui/resources/icons'),
        ('browser_worker.py', '.'),
        ('download_worker.py', '.'),
        ('config.py', '.'),
        ('browser/*.py', 'browser'),
        ('crawler/*.py', 'crawler'),
        ('db/*.py', 'db'),
        ('task/*.py', 'task'),
        ('bizflow/*.py', 'bizflow'),
        ('wechat/*.py', 'wechat'),
        ('gui/*.py', 'gui'),
        ('gui/controllers/*.py', 'gui/controllers'),
        ('gui/services/*.py', 'gui/services'),
        ('gui/pages/*.py', 'gui/pages'),
        ('gui/threads/*.py', 'gui/threads'),
        ('gui/widgets/*.py', 'gui/widgets'),
        ('main.py', '.'),
    ]),
    hiddenimports=[
        'playwright', 'playwright.sync_api', 'playwright._impl',
        'pandas', 'openpyxl', 'pypdf', 'psutil', 'xlrd', 'nest_asyncio',
        'pywechat', 'pyweixin', 'pywinauto', 'pyautogui',
        'comtypes', 'pywin32', 'pycaw', 'sounddevice', 'soundfile',
        'emoji', 'packaging', 'psutil',
        'PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui',
        'qfluentwidgets',
    ] + openai_hiddenimports + pyqt_hiddenimports + fluent_hiddenimports + _wechat_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='林林专属助手-PyQt5',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='林林专属助手-PyQt5',
    upx=True,
    upx_exclude=[],
)
