@echo off
title 🚀 Send Of - Servidor Django
color 0A
echo ============================================
echo    🚀 LIGAR SERVIDOR DJANGO - SEND OF v4
echo ============================================
echo.

:: --- PASSO 1: PostgreSQL ---
echo [1/2] Subindo PostgreSQL...
wsl docker start sendof-postgres 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] Container nao existe. Criando...
    wsl docker run -d --name sendof-postgres ^
        -e POSTGRES_USER=send_of ^
        -e POSTGRES_PASSWORD=send_of ^
        -e POSTGRES_DB=sccj ^
        -p 5433:5432 ^
        postgres:16
    timeout /t 5 /nobreak >nul
)
echo [OK] PostgreSQL rodando!
echo.

:: --- PASSO 2: Django ---
echo [2/2] Subindo Django...
echo.
wsl -d Ubuntu -- bash -l -c "cd ~/PythonProjects/send_of_v4 && source .venv/bin/activate && python manage.py runserver 0.0.0.0:8000"

echo.
echo ============================================
echo    ✅ Servidor iniciado em:
echo       http://localhost:8000
echo ============================================
pause
