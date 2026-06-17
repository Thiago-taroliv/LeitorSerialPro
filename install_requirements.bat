@echo off
REM ============================================================
REM Script de Instalação de Dependências Python
REM Projeto: Leitor Serial Pro
REM ============================================================

chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   Instalador de Dependências - Leitor Serial Pro
echo ============================================================
echo.

REM Verifica se Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ✗ Python não está instalado ou não está no PATH.
    echo.
    echo Execute primeiro o arquivo: install_python.bat
    echo.
    pause
    goto end
)

echo ✓ Python detectado:
python --version
echo.

REM Verifica se o arquivo requirements.txt existe
if not exist "requirements.txt" (
    echo ✗ Arquivo requirements.txt não encontrado.
    echo Certifique-se de estar na pasta correta.
    echo.
    pause
    goto end
)

echo ============================================================
echo   Atualizando pip...
echo ============================================================
python -m pip install --upgrade pip

if %errorlevel% neq 0 (
    echo ✗ Erro ao atualizar pip.
    pause
    goto end
)

echo.
echo ✓ pip atualizado.
echo.
echo ============================================================
echo   Instalando pacotes do requirements.txt...
echo ============================================================
echo.

python -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo ✗ Houve um erro ao instalar alguns pacotes.
    echo.
    echo Tente novamente manualmente com:
    echo   python -m pip install -r requirements.txt
    echo.
    pause
    goto end
)

echo.
echo ============================================================
echo   ✓ Sucesso! Todos os pacotes foram instalados.
echo ============================================================
echo.
echo Pacotes instalados:
python -m pip list
echo.
echo Você pode agora executar o programa com:
echo   python main.py
echo.
pause
goto end

:end
endlocal
