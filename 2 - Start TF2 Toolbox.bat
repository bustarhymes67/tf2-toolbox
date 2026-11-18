@echo off
rem Starts TF2 Toolbox without a console window; this window closes right away.
rem Stop it with the X in the toolbox window (F9 shows it). Messages go to app\scanner.log.
cd /d "%~dp0"
rem Python: on the PATH, or where the install put it (Windows adds it to the PATH only after a restart).
set "PYW=pythonw"
python --version >nul 2>&1 && goto :run
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
if not "%PYW%"=="pythonw" goto :run
echo Python is not installed. Open "1 - Install.bat" first.
pause
exit /b 1
:run
start "" "%PYW%" app\tf2_lobby_scanner.py
