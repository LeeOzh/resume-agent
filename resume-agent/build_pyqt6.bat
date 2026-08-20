@echo off
setlocal
cd /d "%~dp0"
set QT_BINDING=pyqt6
set PY=%~dp0..\venvs\pyqt6_env\Scripts\python.exe
if not exist "%PY%" set PY=C:\Users\cba\AppData\Local\Programs\Python\Python312\python.exe
echo [PyQt6] 使用解释器: %PY%
"%PY%" -m PyInstaller --noconfirm --clean build_gui_pyqt6.spec
echo [PyQt6] 打包完成: dist\林林专属助手-PyQt6\
endlocal
