@echo off
setlocal

:: Step 1: Show the user options
:menu
cls
echo ================================
echo    Python Virtual Environment
echo ================================
echo 1. Create Python environment
echo 2. Activate Python environment
echo 3. Install requirements
echo 4. Deactivate Python environment
echo 5. Exit
echo ================================
set /p choice="Choose an option (1-5): "

:: Step 2: Handle user choice
if "%choice%"=="0" goto enable_scripts
if "%choice%"=="1" goto create_env
if "%choice%"=="2" goto activate_env
if "%choice%"=="3" goto install_requirements
if "%choice%"=="4" goto deactivate_env
if "%choice%"=="5" goto exit_script
goto menu


:: Step 3: Create Python environment
:enable_scripts
echo Enablel running Scripts...
Set-ExecutionPolicy unrestricted
echo Running Scripts enabled.
pause
goto menu


:: Step 3: Create Python environment
:create_env
echo Creating Python virtual environment...
python -m venv myenv
echo Virtual environment created.
pause
goto menu

:: Step 4: Activate Python environment
:activate_env
echo Activating Python virtual environment...
call myenv\Scripts\activate
echo Virtual environment activated.
pause
goto menu

:: Step 5: Install requirements from requirements.txt
:install_requirements
echo Installing requirements from requirements.txt...
pip install -r requirements.txt
echo Requirements installed.
pause
goto menu

:: Step 6: Deactivate Python environment
:deactivate_env
echo Deactivating Python virtual environment...
call myenv\Scripts\deactivate
echo Virtual environment deactivated.
pause
goto menu

:: Step 7: Exit the script
:exit_script
echo Exiting the script...
exit