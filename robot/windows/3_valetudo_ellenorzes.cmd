@echo off
cd /d "%~dp0.."
python run_on_vacuum.py valetudo_verify.sh
python -c "import urllib.request;print(urllib.request.urlopen('http://192.168.1.126/api/v2/robot',timeout=8).read()[:400])" > valetudo_pc_http.txt 2>&1
type valetudo_pc_http.txt
timeout /t 20
