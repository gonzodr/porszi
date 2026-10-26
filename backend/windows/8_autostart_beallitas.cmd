@echo off
rem A gyujto (+dashboard) automatikus inditasa bejelentkezeskor: parancsikon az Inditopult mappaba.
cd /d "%~dp0.."
set "BK=%CD%"
powershell -NoProfile -Command "$py=(Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source; if(-not $py){$py=(Get-Command python.exe).Source}; $s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Porszi gyujto.lnk'); $s.TargetPath=$py; $s.Arguments='\"%BK%\collector.py\"'; $s.WorkingDirectory='%BK%'; $s.WindowStyle=7; $s.Save(); Write-Host ('Kesz: ' + $s.FullName)"
timeout /t 15
