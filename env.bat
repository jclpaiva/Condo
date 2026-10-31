@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:menu
cls
echo ================================
echo    Python Virtual Environment
echo ================================
echo 1. Create Python environment
echo 2. Activate Python environment
echo 3. Install requirements
echo 4. Deactivate Python environment
echo 5. Enable PowerShell scripts (ExecutionPolicy)
echo 6. Exit
echo ================================
set /p choice="Choose an option (1-6): "

if "%choice%"=="1" goto create_env
if "%choice%"=="2" goto activate_env
if "%choice%"=="3" goto install_requirements
if "%choice%"=="4" goto deactivate_env
if "%choice%"=="5" goto enable_scripts
if "%choice%"=="6" goto exit_script
goto menu

:enable_scripts
echo Enabling script execution for CurrentUser...
powershell -NoProfile -Command "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force"
powershell -NoProfile -Command "Remove-Item (Get-PSReadLineOption).HistorySavePath -Force"
if errorlevel 1 (
    echo Failed. Try running this script as Administrator.
) else (
    echo Execution policy updated (CurrentUser / RemoteSigned).
)
pause
goto menu

:create_env
echo Creating Python virtual environment in "myenv"...
where python >nul 2>&1
if errorlevel 1 (
    echo python not found in PATH. Trying "py"...
    py -3 -m venv myenv
) else (
    python -m venv myenv
)
if exist "myenv\Scripts\python.exe" (
    echo Virtual environment created.
) else (
    echo Failed to create virtual environment.
)
pause
goto menu

:activate_env
if not exist "myenv\Scripts\activate.bat" (
    echo Environment not found. Create it first (option 1).
    pause
    goto menu
)
echo Activating Python virtual environment...
call "myenv\Scripts\activate.bat"
echo Virtual environment activated for this window.
echo python:
where python
pause
goto menu

:install_requirements
if not exist "requirements.txt" (
    echo requirements.txt not found in %cd%
    pause
    goto menu
)
if not exist "myenv\Scripts\python.exe" (
    echo Environment not found. Create it first (option 1).
    pause
    goto menu
)
echo Installing requirements into the virtual environment...
call "myenv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo Requirements installed.
pause
goto menu

:deactivate_env
echo Deactivating Python virtual environment...
call deactivate 2>nul
if errorlevel 1 (
    echo No active virtual environment in this window.
) else (
    echo Virtual environment deactivated.
)
pause
goto menu

:exit_script
echo Exiting...
endlocal
exit /b 0