@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m scripts.init_config
if errorlevel 1 goto failed
echo Ready. Edit .env, then read START_HERE_RU.md.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.12 and check the error above.
pause
exit /b 1
