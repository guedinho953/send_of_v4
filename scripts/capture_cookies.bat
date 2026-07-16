@echo off
REM capture_cookies.bat - Roda no Windows (cmd/powershell)
REM Captura cookies do Firefox e salva em D:\Projudi\cookies.json

echo ==========================================
echo  Captura de Cookies do Projudi
echo ==========================================
echo.
echo Requisitos:
echo  - Firefox aberto e logado no Projudi
echo  - Python instalado no Windows
echo  - pip install browser_cookie3
echo.

python -c "import browser_cookie3; print('OK')" 2>nul
if errorlevel 1 (
    echo [ERRO] browser_cookie3 nao instalado
    echo Instale com: pip install browser_cookie3
    pause
    exit /b 1
)

python scripts\capture_cookies_windows.py
pause
