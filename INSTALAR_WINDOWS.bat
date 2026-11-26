@echo off
REM ============================================================
REM  send_of_v4 - INSTALACAO no Windows nativo (venv)
REM  Requer Python 3.12 ou 3.13 instalado (python.org).
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo  send_of_v4 - instalacao para Windows + Firefox local
echo ============================================================
echo.

set "PYLAUNCHER="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 --version >nul 2>&1 && set "PYLAUNCHER=py -3.12"
    if not defined PYLAUNCHER set "PYLAUNCHER=py -3"
)
if not defined PYLAUNCHER (
    where python >nul 2>&1 && set "PYLAUNCHER=python"
)
if not defined PYLAUNCHER (
    echo [ERRO] Python nao encontrado.
    echo        Instale o Python 3.12 em https://www.python.org/downloads/
    echo        e marque a opcao "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Criando ambiente virtual .venv ...
    %PYLAUNCHER% -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar o .venv.
        pause
        exit /b 1
    )
) else (
    echo [1/6] Ambiente virtual .venv ja existe.
)

set "PYTHON=%CD%\.venv\Scripts\python.exe"

echo [2/6] Atualizando pip ...
"%PYTHON%" -m pip install --upgrade pip

echo [3/6] Instalando dependencias (requirements-windows.txt) ...
"%PYTHON%" -m pip install -r requirements-windows.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias.
    pause
    exit /b 1
)

echo [4/6] Baixando o Firefox do Playwright ...
set "PLAYWRIGHT_BROWSERS_PATH="
"%PYTHON%" -m playwright install firefox
if errorlevel 1 (
    echo [AVISO] Nao foi possivel baixar o Firefox do Playwright.
    echo         Verifique a internet e rode novamente este instalador.
)

if not exist ".env" (
    echo [5/6] Criando .env a partir de env.windows.example ...
    copy /Y "env.windows.example" ".env" >nul
) else (
    echo [5/6] .env ja existe - mantido.
)

echo [6/6] Aplicando migracoes e coletando estaticos ...
findstr /i "postgres://" .env >nul 2>&1
if not errorlevel 1 (
    echo [pg] Iniciando PostgreSQL local do projeto...
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\postgres_local_windows.ps1
    if errorlevel 1 (
        echo [AVISO] PostgreSQL nao iniciou. Veja o erro acima.
    )
)
"%PYTHON%" manage.py migrate --noinput
"%PYTHON%" manage.py collectstatic --noinput >nul
"%PYTHON%" manage.py criar_usuario_local

echo.
echo ============================================================
echo  Instalacao concluida!
echo.
echo  Para iniciar: dê duplo clique em RODAR_WINDOWS.bat
echo  Login inicial: admin@local / admin123
echo  (troque a senha em /admin/ depois do primeiro acesso)
echo ============================================================
pause
endlocal
