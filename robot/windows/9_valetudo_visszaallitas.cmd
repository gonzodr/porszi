@echo off
cd /d "%~dp0.."
python run_on_vacuum.py valetudo_restore.sh
echo.
echo Kesz. Ezt az ablakot be lehet zarni.
timeout /t 30
