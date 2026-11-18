@echo off
title TF2 Toolbox - Install
cd /d "%~dp0"

rem 1. Python. The Microsoft Store shortcut "python" doesn't count: it only opens the Store.
set "PY=python"
python --version >nul 2>&1 && goto :have_python
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not "%PY%"=="python" goto :have_python

echo Python is not installed. The setup installs it now (free, from python.org, through winget).
winget --version >nul 2>&1 || goto :no_winget
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if "%PY%"=="python" goto :no_winget
goto :have_python

:no_winget
echo.
echo Python could not be installed automatically.
echo 1. A page opens: download Python and start the installer.
echo 2. On the first screen, select "Add python.exe to PATH". Click "Install Now".
echo 3. Open "1 - Install.bat" again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:have_python
rem 2. The extra Python packages the toolbox needs: pictures, time zones and its window (pywebview).
echo Installing the Python packages the toolbox needs...
"%PY%" -m pip install --user --quiet --disable-pip-version-check -r app\requirements.txt
if errorlevel 1 echo Some packages could not be installed. Run this again; the toolbox needs them to start.

rem 3. Everything else: Steam, TF2 launch options, keys, HoovyGPT, the cheat check.
"%PY%" app\tf2_setup.py
pause
