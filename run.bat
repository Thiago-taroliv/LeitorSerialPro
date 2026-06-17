@echo off
REM ============================================================
REM Script para executar o Leitor Serial Pro
REM ============================================================

chcp 65001 >nul

echo.
echo ============================================================
echo   Leitor Serial Pro
echo ============================================================
echo.

REM Verifica se Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ✗ Python não está instalado.
    echo.
    echo Execute primeiro: install_python.bat
    echo.
    pause
    goto end
)

REM Verifica se main.py existe
if not exist "main.py" (
    echo ✗ Arquivo main.py não encontrado.
    echo.
    pause
    goto end
)

echo ✓ Iniciando aplicação...
echo.

REM Executa o programa
python main.py

goto end

:end
