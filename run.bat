@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=%LOCALAPPDATA%\Programs\PyEmbed312\python.exe
if not exist "%PY%" set PY=.venv\Scripts\python.exe
"%PY%" main.py
pause
