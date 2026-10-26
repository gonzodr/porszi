@echo off
cd /d "%~dp0.."
python collector.py --test-notify
echo.
timeout /t 20
