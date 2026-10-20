@echo off
cd /d "%~dp0"
if exist "D:\mamba\python.exe" (
  "D:\mamba\python.exe" host\app.py
) else (
  python host\app.py
)
if errorlevel 1 pause
