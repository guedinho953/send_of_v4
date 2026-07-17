#!/bin/bash
# Backup automático do PostgreSQL send_of_v4
# Salva dump SQL + copia para a pasta do projeto

BACKUP_DIR="$HOME/PythonProjects/send_of_v4/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DUMP_FILE="$BACKUP_DIR/sendof_${TIMESTAMP}.sql"

# Criar diretório se não existir
mkdir -p "$BACKUP_DIR"

# Fazer o dump
docker exec pg_send_of pg_dump -U send_of sccj > "$DUMP_FILE" 2>/tmp/pg_backup_err.log

if [ $? -eq 0 ]; then
    # Comprimir
    gzip -f "$DUMP_FILE"
    echo "Backup OK: ${DUMP_FILE}.gz ($(du -h ${DUMP_FILE}.gz | cut -f1))"
    
    # Manter apenas os 7 backups mais recentes
    ls -t "$BACKUP_DIR"/sendof_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm
else
    echo "ERRO no backup: $(cat /tmp/pg_backup_err.log)"
    exit 1
fi
