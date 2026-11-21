@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -c "import xlsxwriter" 2>nul
if not errorlevel 1 goto export
.venv\Scripts\python.exe -m pip install "XlsxWriter>=3,<4"
if errorlevel 1 goto done
:export
.venv\Scripts\python.exe -m scripts.export_excel %*
:done
pause
