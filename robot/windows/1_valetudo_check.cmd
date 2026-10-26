@echo off
cd /d "%~dp0.."
python run_on_vacuum.py valetudo_check.sh
echo.
echo Kesz. Ezt az ablakot be lehet zarni.
timeout /t 15
