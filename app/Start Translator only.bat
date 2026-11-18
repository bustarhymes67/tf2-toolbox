@echo off
title TF2 Chat Translator
rem Only the chat translator, without the scanner (the scanner already includes it).
cd /d "%~dp0"
rem Python: on the PATH, or where the install put it (Windows adds it to the PATH only after a restart).
set "PY=python"
python --version >nul 2>&1 && goto :run
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not "%PY%"=="python" goto :run
echo Python is not installed. Open "1 - Install.bat" first.
pause
exit /b 1
:run
"%PY%" tf2_translator.py
pause
