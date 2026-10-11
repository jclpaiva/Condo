@echo off
chcp 65001 >nul
cls
echo.
echo ========================================
echo  GestaoCondominio - Build Script
echo ========================================
echo.

REM Verificar se Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ ERRO: Python não encontrado!
    echo    Instale Python primeiro.
    pause
    exit /b 1
)

REM Verificar se PyInstaller está instalado
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo ⚠️  PyInstaller não encontrado. Instalando...
    pip install pyinstaller
)

REM Executar build
echo 🚀 Iniciando build...
echo.
python build.py

if errorlevel 1 (
    echo.
    echo ❌ Build falhou!
    pause
    exit /b 1
)

echo.
echo ✅ Build concluído!
echo.
pause