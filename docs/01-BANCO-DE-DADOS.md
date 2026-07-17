# 🗄️ 01 — Banco de Dados PostgreSQL

## Data: 2026-07-17

---

## Problema Original

O Django não subia porque o PostgreSQL não estava rodando.

```
django.db.utils.OperationalError: connection to server at "localhost" (127.0.0.1), port 5433 failed: Connection refused
```

O PostgreSQL estava configurado no `.env` como:
```
DATABASE_URL=postgres://send_of:send_of@localhost:5433/sccj
```

---

## Container Correto

Existem DOIS containers que já existiram:

| Container | Volume | Status | Dados |
|-----------|--------|--------|-------|
| `pg_send_of` | `e905eb2a8cf...` (50.46 MB) | Original, **parado** | ✅ 74 processos, 814 RAGs |
| `sendof-postgres` | `send_of_v4_pgdata` (67.23 MB) | Criado por engano | ❌ Só admin, zerado |

**ERRO COMETIDO:** O Hermes criou um container NOVO (`sendof-postgres`) com o
volume `send_of_v4_pgdata` (que estava vazio, só tinha auth tables). O container
original `pg_send_of` (com os dados reais) estava parado e foi ignorado.

**LIÇÃO:** Sempre verificar `docker ps -a` para encontrar containers parados
antes de criar novos.

## Comandos

```bash
# Subir o banco (após reiniciar o PC)
docker start pg_send_of

# Verificar se está rodando
docker ps --filter name=pg_send_of

# Recriar o container (se necessário)
docker run -d \
  --name pg_send_of \
  -e POSTGRES_USER=send_of \
  -e POSTGRES_PASSWORD=send_of \
  -e POSTGRES_DB=sccj \
  -v send_of_v4_pgdata:/var/lib/postgresql/data \
  -p 5433:5432 \
  postgres:16

# ⚠️ SEMPRE usar -v send_of_v4_pgdata:/var/lib/postgresql/data
# Senão perde os dados!
```

## Verificar dados no banco

```bash
cd ~/PythonProjects/send_of_v4
source .venv/bin/activate
python manage.py shell -c "
from accounts.models import User
from processes.models import Process, RAGExample
print(f'Usuários: {User.objects.count()}')
print(f'Processos: {Process.objects.count()}')
print(f'RAGs: {RAGExample.objects.count()}')
"
```

---

## Backup Externo

**Script:** `scripts/backup_db.sh`

Faz `pg_dump` do container `pg_send_of`, comprime em `.sql.gz`,
mantém os 7 mais recentes.

```bash
# Manual
bash scripts/backup_db.sh

# Automático (cron Hermes todo dia às 03:00)
```

**Local dos backups:**
```
~/PythonProjects/send_of_v4/backups/
```

---

## Login

| Email | Senha |
|-------|-------|
| `admin@admin.com` | (a mesma de antes) |

---

## Arquivos

| Arquivo | Conteúdo |
|---------|----------|
| `CONFIG_BANCO.md` | Guia rápido de configuração do banco |
| `LIGAR_SERVIDOR.md` | Comandos para subir o servidor |
| `LIGAR_SERVIDOR.bat` | Atalho Windows (duplo clique) |
| `scripts/backup_db.sh` | Script de backup automático |
