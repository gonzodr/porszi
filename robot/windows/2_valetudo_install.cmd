@echo off
cd /d "%~dp0.."
python install_valetudo.py
echo.
echo Kesz. Ezt az ablakot be lehet zarni.
timeout /t 30
