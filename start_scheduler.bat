@echo off
chcp 65001 >nul
title KHunter - Daily Scheduler (17:00)
cd /d "%~dp0"
echo Starting KHunter daily scheduler...
echo Task: data update + selection + save, every day at 17:00 (trading days only)
echo Log: logs\daily_scheduler.log
echo.
.venv\Scripts\python.exe daily_scheduler.py
pause
