@echo off
cd /d "%~dp0.."
echo Porszi gyujto - 60 masodperces probafutas...
python collector.py --for 60
echo.
python report.py
echo.
echo Kesz. Ezt az ablakot be lehet zarni.
timeout /t 60
