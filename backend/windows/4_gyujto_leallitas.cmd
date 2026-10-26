@echo off
echo Porszi gyujto leallitasa...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*collector.py*' -and $_.Name -like 'python*' } | ForEach-Object { Write-Host ('Leallitva: PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"
timeout /t 10
