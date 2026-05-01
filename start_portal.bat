@echo off
setlocal

cd /d "%~dp0"

echo Installing requirements if needed...
python -m pip install --user -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

echo Starting server on http://127.0.0.1:8085/
echo Keep this terminal open while using the portal.
python server.py

endlocal
