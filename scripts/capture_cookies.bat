@echo off
REM capture_cookies.bat - Roda no Windows (cmd/powershell)
REM Captura cookies do Firefox e salva em D:\Projudi\cookies.json
REM
REM Use duplo clique ou:
REM   scripts\capture_cookies.bat
REM
REM Para capturar uma vez e sair:
REM   scripts\capture_cookies.bat --quiet

title Captura de Cookies - Projudi

echo ==========================================
echo  Captura de Cookies do Projudi
echo ==========================================
echo.
echo Requisitos:
echo  - Firefox aberto e logado no Projudi
echo  - Python instalado no Windows
echo  - browser_cookie3 instalado
echo.

REM O script usa %~dp0 (pasta deste .bat), entao funciona mesmo
REM quando o cmd abre em outro diretorio.
python -c "import browser_cookie3" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] browser_cookie3 nao instalado. Instalando...
    python -m pip install browser_cookie3
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar browser_cookie3
        pause
        exit /b 1
    )
)

echo.
echo Capturando cookies...
REM --quiet captura uma vez e sai. Para keep-alive, rode o .py sem --quiet.
python "%~dp0capture_cookies_windows.py" --quiet %*
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao capturar cookies.
    echo        Verifique se:
    echo        1. O Firefox esta aberto
    echo        2. Voce esta logado em https://projudi.tjba.jus.br
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Cookies capturados com sucesso!
echo  Arquivo: D:\Projudi\cookies.json
echo ==========================================
echo.
pause
