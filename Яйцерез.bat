@echo off
rem Запуск Яйцереза без консольного окна
cd /d "%~dp0"
if exist ".venv\Scripts\Yaitserez.exe" (start "" ".venv\Scripts\Yaitserez.exe" app.py %*) else (start "" ".venv\Scripts\pythonw.exe" app.py %*)
