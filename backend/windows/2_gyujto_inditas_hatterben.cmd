@echo off
cd /d "%~dp0.."
for %%P in (python.exe) do set "PYDIR=%%~dp$PATH:P"
if exist "%PYDIR%pythonw.exe" (
  start "" "%PYDIR%pythonw.exe" "%~dp0..\collector.py"
  echo A gyujto elindult a hatterben. Naplo: collector.log
) else (
  start "Porszi gyujto" /min python "%~dp0..\collector.py"
  echo A gyujto elindult egy kicsinyitett ablakban.
)
timeout /t 10
