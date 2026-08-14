# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 收集 openai 及其所有依赖
openai_datas, openai_binaries, openai_hiddenimports = collect_all('openai')

# 收集 PyQt6 及其所有依赖
pyqt6_datas, pyqt6_binaries, pyqt6_hiddenimports = collect_all('PyQt6')

# wechat monitor: pywechat127 (pyweixin) and its dependency chain.
# skip collection gracefully when a package is not installed on the build machine.
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
    binaries=(openai_binaries + pyqt6_binaries + _wechat_binaries),
    datas=(openai_datas + pyqt6_datas + _wechat_datas + [
        ('gui/resources/styles/*.qss', 'gui/resources/styles'),
        ('gui/resources/icons/*.svg', 'gui/resources/icons'),
        ('browser_worker.py', '.'),
        ('download_worker.py', '.'),
        ('config.py', '.'),
        ('browser/*.py', 'browser'),
        ('crawler/*.py', 'crawler'),
        ('db/*.py', 'db'),
        ('task/*.py', 'task'),
        ('workflow/*.py', 'workflow'),
        ('wechat/*.py', 'wechat'),
        ('gui/pages/*.py', 'gui/pages'),
        ('main.py', '.'),
    ]),
    hiddenimports=[
        'playwright',
        'playwright.sync_api',
        'playwright._impl',
        'pandas',
        'openpyxl',
        'pypdf',
        'psutil',
        'xlrd',
        'nest_asyncio',
        'pywechat', 'pyweixin', 'pywinauto', 'pyautogui',
        'comtypes', 'pywin32', 'pycaw', 'sounddevice', 'soundfile',
        'emoji', 'packaging', 'psutil',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
    ] + openai_hiddenimports + pyqt6_hiddenimports + _wechat_hiddenimports,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='林林专属助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI版本不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
