@echo off
REM ============================================================
REM Script de Instalação de Python e Dependências
REM Projeto: Leitor Serial Pro
REM ============================================================

chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   Instalador de Python - Leitor Serial Pro
echo ============================================================
echo.

REM Verifica se Python está instalado
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ Python já está instalado:
    python --version
    echo.
    echo Deseja prosseguir com a instalação de dependências? (S/N)
    set /p choice=
    if /i not "!choice!"=="S" goto end
    goto install_requirements
)

echo ⚠ Python não foi detectado no sistema.
echo.
echo Opções:
echo 1 - Baixar e instalar Python 3.11 (Recomendado)
echo 2 - Baixar e instalar Python 3.12 (Mais Recente)
echo 3 - Cancelar
echo.
set /p option="Escolha uma opção (1-3): "

if "!option!"=="1" (
    set PYTHON_VERSION=3.11.9
    set PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    goto download_python
) else if "!option!"=="2" (
    set PYTHON_VERSION=3.12.4
    set PYTHON_URL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe
    goto download_python
) else (
    echo Instalação cancelada.
    goto end
)

:download_python
echo.
echo Baixando Python !PYTHON_VERSION!...
set INSTALLER=%TEMP%\python-!PYTHON_VERSION!-amd64.exe

REM Usa PowerShell para baixar o arquivo
powershell -Command "Write-Host 'Aguarde, baixando...'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '!PYTHON_URL!' -OutFile '!INSTALLER!' -UseBasicParsing" 2>nul

if not exist "!INSTALLER!" (
    echo ✗ Erro ao baixar Python. Verifique sua conexão de internet.
    goto end
)

echo ✓ Download concluído.
echo.
echo Instalando Python !PYTHON_VERSION!...
echo Por favor, aguarde...
echo.

REM Executa o instalador com opções silenciosas
"!INSTALLER!" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 >nul 2>&1

if %errorlevel% nequ 0 (
    echo ⚠ A instalação em modo silencioso falhou. Abrindo instalador...
    "!INSTALLER!"
    del "!INSTALLER!"
    goto end
)

del "!INSTALLER!"

REM Aguarda um pouco para o Python ser reconhecido
timeout /t 2 /nobreak >nul

REM Verifica se Python foi instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ✗ Python não foi detectado após a instalação.
    echo Reinicie o computador e tente novamente.
    goto end
)

echo.
echo ✓ Python foi instalado com sucesso!
python --version

:install_requirements
echo.
echo ============================================================
echo   Instalando Dependências
echo ============================================================
echo.

REM Atualiza pip
echo Atualizando pip...
python -m pip install --upgrade pip >nul 2>&1

if %errorlevel% neq 0 (
    echo ✗ Erro ao atualizar pip.
    goto end
)

echo ✓ pip atualizado.
echo.

REM Instala requirements
if exist "requirements.txt" (
    echo Instalando pacotes do requirements.txt...
    echo.
    python -m pip install -r requirements.txt
    
    if %errorlevel% neq 0 (
        echo.
        echo ✗ Houve um erro ao instalar alguns pacotes.
        echo Por favor, tente manualmente: python -m pip install -r requirements.txt
        pause
        goto end
    )
    
    echo.
    echo ✓ Todos os pacotes foram instalados com sucesso!
) else (
    echo ✗ Arquivo requirements.txt não encontrado.
)

echo.
echo ============================================================
echo   Instalação Concluída!
echo ============================================================
echo.
echo Você pode agora executar o programa com:
echo   python main.py
echo.
pause
goto end

:end
endlocal
