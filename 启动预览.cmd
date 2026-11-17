@echo off
rem Bedrock creator collab graph preview launcher
setlocal
set "URL=http://127.0.0.1:8765/"
"C:\Windows\System32\curl.exe" -s -o nul --max-time 2 "%URL%" >nul 2>&1
if not errorlevel 1 (
  start "" "%URL%"
  exit /b 0
)
set "PYTHONIOENCODING=utf-8"
start "collab-graph-server" /D "D:\新建文件夹 (5)" "C:\Users\ZHAO1\AppData\Local\Programs\Python\Python38\python.exe" server.py
"C:\Windows\System32\timeout.exe" /t 2 /nobreak >nul
start "" "%URL%"
