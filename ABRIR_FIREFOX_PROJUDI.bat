@echo off
REM Abre o Projudi no Firefox local (para fazer login antes da captura).
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if exist "%PYTHON%" (
    "%PYTHON%" scripts\abrir_navegador.py "https://projudi.tjba.jus.br/projudi/"
    exit /b 0
)

set "FF=%ProgramFiles%\Mozilla Firefox\firefox.exe"
if not exist "%FF%" set "FF=%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"
if not exist "%FF%" set "FF=%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"

if exist "%FF%" (
    start "" "%FF%" "https://projudi.tjba.jus.br/projudi/"
) else (
    echo [AVISO] Firefox nao encontrado nos caminhos padrao.
    echo         Abrindo com o navegador padrao...
    start "" "https://projudi.tjba.jus.br/projudi/"
)
endlocal
