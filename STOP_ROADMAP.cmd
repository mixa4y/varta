@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\stop_varta_roadmap.ps1" %*
if errorlevel 1 pause
