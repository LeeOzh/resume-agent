@echo off
setlocal
cd /d "%~dp0"
set QT_BINDING=pyqt5
set PY=%~dp0..\venvs\pyqt5_env\Scripts\python.exe
if not exist "%PY%" (
  echo [PyQt5] 未找到 venv: %PY%
  echo 请先执行: python -m venv venvs\pyqt5_env 并安装 requirements\pyqt5.txt
  exit /b 1
)
echo [PyQt5] 使用解释器: %PY%
"%PY%" -m PyInstaller --noconfirm --clean build_gui_pyqt5.spec
echo [PyQt5] 打包完成: dist\林林专属助手-PyQt5\
endlocal
