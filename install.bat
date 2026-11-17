@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "UV=%ROOT%tools\uv\uv.exe"
set "UV_CACHE_DIR=%ROOT%data\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%ROOT%tools\python"
set "UV_HTTP_TIMEOUT=300"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "SILENT="
set "NOSHORTCUT="
rem /silent: run from Yaitserez-Setup.exe - no pauses, the setup window shows the output
for %%A in (%*) do (
  if /i "%%~A"=="/silent" set "SILENT=1"
  if /i "%%~A"=="/noshortcut" set "NOSHORTCUT=1"
)
if defined SILENT (
  set "PYTHONIOENCODING=mbcs:replace"
  set "PYTHONUTF8=0"
  set "NO_COLOR=1"
)
title Yaitserez install

echo.
echo === [1/6] uv (Python manager) ===
if not exist "%UV%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $z=Join-Path $env:TEMP 'yaitserez-uv.zip'; Invoke-WebRequest -UseBasicParsing 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $z; Expand-Archive -Force $z 'tools\uv'"
)
if not exist "%UV%" goto :fail

echo.
echo === [2/6] Python 3.12 ===
if not exist "%PY%" (
  "%UV%" venv --python 3.12 --python-preference only-managed .venv || goto :fail
)

echo.
echo === [3/6] Libraries: speech recognition, window, NVIDIA libraries - about 1.5 GB ===
"%UV%" pip install --python "%PY%" -r requirements.txt || goto :fail

echo.
echo === [4/6] ffmpeg ===
if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $z=Join-Path $env:TEMP 'yaitserez-ffmpeg.zip'; Invoke-WebRequest -UseBasicParsing 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $z; $t=Join-Path $env:TEMP 'yaitserez-ffmpeg'; if (Test-Path $t) { Remove-Item -Recurse -Force $t }; Expand-Archive -Force $z $t; $d=Get-ChildItem $t -Directory | Select-Object -First 1; New-Item -ItemType Directory -Force 'tools\ffmpeg\bin' | Out-Null; Copy-Item (Join-Path $d.FullName 'bin\ffmpeg.exe'),(Join-Path $d.FullName 'bin\ffprobe.exe') 'tools\ffmpeg\bin'; Remove-Item -Recurse -Force $t, $z"
)
if not exist "tools\ffmpeg\bin\ffmpeg.exe" goto :fail

echo.
echo === [5/6] Yaitserez.exe and icon ===
"%PY%" tools\make_icon.py || goto :fail
"%PY%" tools\make_exe.py || goto :fail

echo.
echo === [6/6] Shortcuts ===
if not defined NOSHORTCUT "%PY%" tools\make_shortcut.py || goto :fail

echo.
echo === Done ===
echo The speech model is taken from VoiceType if it is installed; otherwise it is downloaded on first run (about 1.5 GB).
if not defined SILENT pause
exit /b 0

:fail
echo.
echo === Installation failed. See the messages above. ===
if not defined SILENT pause
exit /b 1
