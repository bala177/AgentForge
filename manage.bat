@echo off
setlocal enabledelayedexpansion
:: ============================================================
::  manage.bat — Manage the AI Agent Platform (FastAPI + Uvicorn)
::
::  Usage:  manage.bat {start|stop|restart|status|log|clean|install|help}
:: ============================================================

set "APP_DIR=%~dp0"
set "APP_CMD=python main.py"
set "PID_FILE=%APP_DIR%.app.pid"
set "LOG_FILE=%APP_DIR%app.log"
set "VENV_DIR=%APP_DIR%.venv"
set "PORT=5000"

if "%~1"=="" goto :help
goto :%~1 2>nul || goto :help

:: ── Install ─────────────────────────────────────────────────
:install
echo [INFO]  Creating virtual environment in %VENV_DIR% ...
python -m venv "%VENV_DIR%"
call "%VENV_DIR%\Scripts\activate.bat"
echo [INFO]  Installing dependencies ...
pip install --upgrade pip -q
pip install -r "%APP_DIR%requirements.txt" -q
echo [INFO]  Done. Run  manage.bat start  to launch the app.
goto :eof

:: ── Start ───────────────────────────────────────────────────
:start
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    tasklist /FI "PID eq !OLD_PID!" 2>nul | find "python" >nul 2>&1
    if not errorlevel 1 (
        echo [WARN]  App is already running ^(PID !OLD_PID!^).
        goto :eof
    )
)
if exist "%VENV_DIR%\Scripts\activate.bat" call "%VENV_DIR%\Scripts\activate.bat"
echo [INFO]  Starting server on port %PORT% ...
pushd "%APP_DIR%"
start /B "" %APP_CMD% --port %PORT% >> "%LOG_FILE%" 2>&1
:: Grab the PID of the most-recently launched python process
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| findstr /B "PID:"') do set "NEW_PID=%%a"
echo %NEW_PID%> "%PID_FILE%"
echo [INFO]  Server started ^(PID %NEW_PID%^).  Log: %LOG_FILE%
echo [INFO]  Dashboard:  http://localhost:%PORT%
echo [INFO]  API Docs:   http://localhost:%PORT%/docs
echo [INFO]  WebSocket:  ws://localhost:%PORT%/ws/chat/{session_id}
popd
goto :eof

:: ── Stop ────────────────────────────────────────────────────
:stop
if not exist "%PID_FILE%" (
    echo [WARN]  PID file not found — app may not be running.
    goto :eof
)
set /p PID=<"%PID_FILE%"
echo [INFO]  Stopping app ^(PID %PID%^) ...
taskkill /PID %PID% /F >nul 2>&1
if not errorlevel 1 (
    echo [INFO]  App stopped.
) else (
    echo [WARN]  Process %PID% was not running.
)
del /f "%PID_FILE%" >nul 2>&1
goto :eof

:: ── Restart ─────────────────────────────────────────────────
:restart
call :stop
timeout /t 2 /nobreak >nul
call :start
goto :eof

:: ── Status ──────────────────────────────────────────────────
:status
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    tasklist /FI "PID eq !PID!" 2>nul | find "python" >nul 2>&1
    if not errorlevel 1 (
        echo [INFO]  App is RUNNING ^(PID !PID!, port %PORT%^).
    ) else (
        echo [WARN]  App is NOT RUNNING ^(stale PID file^).
        del /f "%PID_FILE%" >nul 2>&1
    )
) else (
    echo [WARN]  App is NOT RUNNING.
)
goto :eof

:: ── Log ─────────────────────────────────────────────────────
:log
if not exist "%LOG_FILE%" (
    echo [WARN]  No log file found.
    goto :eof
)
set "LINES=%~2"
if "%LINES%"=="" set "LINES=50"
echo [INFO]  Last %LINES% lines of %LOG_FILE%:
echo ────────────────────────────────────────
powershell -Command "Get-Content '%LOG_FILE%' -Tail %LINES%"
goto :eof

:: ── Log follow ──────────────────────────────────────────────
:logf
if not exist "%LOG_FILE%" (
    echo [WARN]  No log file found.
    goto :eof
)
echo [INFO]  Tailing %LOG_FILE%  (Ctrl+C to stop) ...
powershell -Command "Get-Content '%LOG_FILE%' -Wait -Tail 30"
goto :eof

:: ── Clean ───────────────────────────────────────────────────
:clean
echo [INFO]  Cleaning up ...
if exist "%LOG_FILE%" del /f "%LOG_FILE%"
if exist "%PID_FILE%" del /f "%PID_FILE%"
if exist "%APP_DIR%nul" del /f "%APP_DIR%nul" 2>nul
if exist "%APP_DIR%__pycache__" rd /s /q "%APP_DIR%__pycache__"
for /d /r "%APP_DIR%" %%d in (__pycache__) do if exist "%%d" rd /s /q "%%d"
del /s /q "%APP_DIR%*.pyc" >nul 2>&1
echo [INFO]  Cleaned: logs, pid file, __pycache__, *.pyc
goto :eof

:: ── Purge ───────────────────────────────────────────────────
:purge
call :stop 2>nul
call :clean
if exist "%VENV_DIR%" (
    echo [INFO]  Removing virtual environment ...
    rd /s /q "%VENV_DIR%"
)
echo [INFO]  Purge complete.
goto :eof

:: ── CLI ─────────────────────────────────────────────────────
:cli
if exist "%VENV_DIR%\Scripts\activate.bat" call "%VENV_DIR%\Scripts\activate.bat"
pushd "%APP_DIR%"
python main.py --cli
popd
goto :eof

:: ── Help ────────────────────────────────────────────────────
:help
echo.
echo   AI Agent Platform — Management Script (Windows)
echo.
echo   Usage:  manage.bat ^<command^> [args]
echo.
echo   Commands:
echo     install       Create venv and install dependencies
echo     start         Start the FastAPI server in background
echo     stop          Stop the running server
echo     restart       Stop + start
echo     status        Check if the server is running
echo     log [N]       Show last N lines of log  (default: 50)
echo     logf          Tail the log (live follow)
echo     clean         Remove logs, pid file, __pycache__
echo     purge         clean + remove venv
echo     cli           Run the interactive CLI  (main.py --cli)
echo     help          Show this help message
echo.
goto :eof
