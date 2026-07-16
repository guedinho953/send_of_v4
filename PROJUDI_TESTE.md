# TESTE REAL - Sistema de Oficios

## SERVIDOR
Ja esta rodando em: http://localhost:8000

## LOGIN
- Email: igusilva@tjba.jus.br
- Senha: admin123

## DASHBOARD DE OFICIOS
http://localhost:8000/projudi/oficios/dashboard/

## PARA SINCRONIZAR OFICIOS REAIS (passo a passo)

### Passo 1: No Windows (cmd/powershell)
Abra o cmd/powershell NO WINDOWS (nao no WSL) e rode:

```cmd
cd C:\caminho\para\send_of_v4
python scripts\capture_cookies_windows.py
```

Ou mais simples:
```cmd
python scripts\capture_cookies_windows.py
```

Isso cria: `D:\Projudi\cookies.json`

### Passo 2: No Django (ja esta rodando)
Acesse no navegador: http://localhost:8000/projudi/oficios/dashboard/
Faca login com igusilva@tjba.jus.br / admin123
Clique em "Sincronizar com Projudi"

### Resultado esperado
- Se cookies validos: "X oficios sincronizados"
- Se cookies invalidos: "Sessao expirada" ou "Nao foi possivel capturar"

## PROBLEMAS COMUNS
1. "Nao foi possivel capturar a sessao" -> Rode o script no Windows primeiro
2. "NOT NULL constraint" -> JA FOI CORRIGIDO
3. "Sessao expirada" -> Firefox fechou, reabra e rode o script novamente

## COMANDOS UTEIS
```bash
# Verificar se servidor esta rodando
curl http://localhost:8000/health/

# Parar servidor
pkill -f "manage.py runserver"

# Reiniciar servidor
cd /home/ivan/PythonProjects/send_of_v4
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000 --noreload
```
