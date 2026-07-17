# 🗄️ Configuração do PostgreSQL — send_of_v4

## Container correto

O banco de dados roda no container **`pg_send_of`** com o volume **`send_of_v4_pgdata`**.

⚠️ **Já teve problema com container errado!** O Hermes criou um `sendof-postgres` (sem underline) que estava vazio. O correto é `pg_send_of`.

```
Container: pg_send_of
Imagem:    postgres:16
Porta:     5433 → 5432 (host → container)
Volume:    send_of_v4_pgdata → /var/lib/postgresql/data
```

## Subir o banco (após reiniciar o PC)

```bash
docker start pg_send_of
```

## Recriar o container (se precisar)

```bash
docker run -d \
  --name pg_send_of \
  -e POSTGRES_USER=send_of \
  -e POSTGRES_PASSWORD=send_of \
  -e POSTGRES_DB=sccj \
  -v send_of_v4_pgdata:/var/lib/postgresql/data \
  -p 5433:5432 \
  postgres:16
```

**⚠️ Atenção:** Sempre usar `-v send_of_v4_pgdata:/var/lib/postgresql/data` senão perde os dados!

## Backup externo (espelhado fora do Docker)

### Local dos backups
```
~/PythonProjects/send_of_v4/backups/
```

### Como funciona
- Um **cron job do Hermes** roda todo dia às **03:00**
- Executa `pg_dump` no container `pg_send_of`
- Comprime o dump em `.sql.gz`
- Mantém os **7 backups mais recentes**

### Backup manual
```bash
bash ~/PythonProjects/send_of_v4/scripts/backup_db.sh
```

### Restaurar um backup
```bash
# Listar backups disponíveis
ls -lh ~/PythonProjects/send_of_v4/backups/

# Restaurar o mais recente
zcat ~/PythonProjects/send_of_v4/backups/sendof_$(ls -t ~/PythonProjects/send_of_v4/backups/ | head -1) | docker exec -i pg_send_of psql -U send_of sccj
```

## Criar um backup agora
```bash
cd ~/PythonProjects/send_of_v4
source .venv/bin/activate
bash scripts/backup_db.sh
```

## Problemas comuns

### "collation version mismatch"
```bash
docker exec pg_send_of psql -U send_of sccj -c "ALTER DATABASE sccj REFRESH COLLATION VERSION"
```

### Porta 5433 ocupada
```bash
kill $(lsof -ti:5433)
```

### Quer usar um volume diferente
Listar volumes existentes:
```bash
docker volume ls | grep pg
```
