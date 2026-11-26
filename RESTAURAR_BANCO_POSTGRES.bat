@echo off
REM ============================================================
REM  Restaura um dump do PostgreSQL (ex.: exportado do Docker
REM  pg_send_of no Ubuntu) no PostgreSQL local do projeto.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo  Restaurar banco PostgreSQL no Windows
echo ============================================================
echo.
echo Arraste o arquivo .sql / .sql.gz / .dump para esta janela
echo e pressione Enter. (Ou digite o caminho completo.)
echo.
set /p "DUMP=Arquivo: "
set "DUMP=%DUMP:"=%"

if not exist "%DUMP%" (
    echo [ERRO] Arquivo nao encontrado: %DUMP%
    pause
    exit /b 1
)

echo.
echo [1/2] Restaurando em PostgreSQL local (porta 5433)...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\postgres_local_windows.ps1 -DumpFile "%DUMP%"
if errorlevel 1 (
    echo [ERRO] Falha ao restaurar o dump.
    pause
    exit /b 1
)

echo.
echo [2/2] Aplicando migracoes do Django...
".venv\Scripts\python.exe" manage.py migrate --noinput
".venv\Scripts\python.exe" manage.py check

echo.
echo [OK] Restauracao concluida. Inicie com RODAR_WINDOWS.bat
pause
endlocal
