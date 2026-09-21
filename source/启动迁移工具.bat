@echo off
chcp 936 >nul
cd /d "%~dp0"
title 霸主 tpac 迁移工具

rem ============================================================
rem  启动前先找一个"带 tkinter"的 Python，避免缺组件时白屏闪退
rem ============================================================
set "PY="

call :pick "py -3"
if not defined PY call :pick "py"
if not defined PY call :pick "python"
if not defined PY call :pick "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY call :pick "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :pick "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :pick "C:\Python311\python.exe"

if not defined PY (
  echo.
  echo   [!] 没有找到可用的 Python。
  echo.
  echo   本工具需要 Python 3.8 以上，且安装时必须勾选
  echo   "tcl/tk and IDLE" 组件（否则图形界面无法启动）。
  echo.
  echo   请到 python.org 下载安装，或手动修改本文件中的 Python 路径。
  echo.
  pause
  exit /b 1
)

echo   启动中：%PY%
echo.
%PY% migrator_gui.py %*
if errorlevel 1 (
  echo.
  echo   [!] 程序异常退出。若提示缺少 tkinter，请重新安装 Python 并勾选 tcl/tk 组件。
  echo.
  pause
)
exit /b 0

:pick
%~1 -c "import tkinter" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
goto :eof
