@echo off
cd /d "%~dp0.."
python dashboard_check.py
timeout /t 15
