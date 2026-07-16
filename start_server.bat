@echo off
echo ==========================================
echo  INICIAR SERVIDOR DJANGO - Send of v4
echo ==========================================
echo.
echo Abrindo servidor na porta 8000...
echo.
echo Aguarde 5 segundos...
echo.

wsl -d Ubuntu -u ivan bash -c "cd /home/ivan/PythonProjects/send_of_v4 && source .venv/bin/activate && python manage.py runserver 0.0.0.0:8000 --noreload &"

timeout /t 6 /nobreak > nul

echo.
echo ==========================================
echo  SERVIDOR INICIADO!
echo ==========================================
echo.
echo Acesse no navegador:
echo   http://localhost:8000
echo.
echo Login:
echo   Email: igusilva@tjba.jus.br
echo   Senha: admin123
echo.
echo Oficios:
echo   http://localhost:8000/projudi/oficios/dashboard/
echo.
pause