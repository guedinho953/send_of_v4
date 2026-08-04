#!/bin/bash
# Restauração / espelhamento do banco PostgreSQL send_of_v4 a partir de um dump.
#
# Uso:  ./scripts/restaurar_db.sh [caminho_do_dump.sql.gz | caminho_do_dump.sql]
#   - sem argumento: usa o backup .sql.gz mais recente em backups/
#   - com .gz : descomprime na hora
#
# ALERTA: isto DESTRÓI o conteúdo atual do banco e restaura o dump.
# Esse é o "espelhamento": levar um backup a um outro Postgres (ou recuperar).

set -e

BACKUP_DIR="$HOME/PythonProjects/send_of_v4/backups"
DUMP_SRC="${1:-$(ls -t "$BACKUP_DIR"/sendof_*.sql.gz 2>/dev/null | head -1)}"

if [ -z "$DUMP_SRC" ] || [ ! -f "$DUMP_SRC" ]; then
    echo "❌ Nenhum dump encontrado em $BACKUP_DIR (ou caminho inválido)."
    exit 1
fi

echo "Restaurando: $DUMP_SRC"
echo "⚠️  Isso SUBSTITUI o conteúdo atual do banco sccj."
echo "Quer continuar? (s/N)"
read -r CONFIRM
if [ "$CONFIRM" != "s" ] && [ "$CONFIRM" != "S" ]; then
    echo "Cancelado."
    exit 1
fi

# Descomprime se .gz
TMP_SQL=""
if [[ "$DUMP_SRC" == *.gz ]]; then
    TMP_SQL=$(mktemp /tmp/restore_XXXXXX.sql)
    gzip -dc "$DUMP_SRC" > "$TMP_SQL"
    DUMP_SRC="$TMP_SQL"
fi

# Recria o banco limpo e restaura
docker exec pg_send_of psql -U send_of -d postgres -c "DROP DATABASE IF EXISTS sccj" >/dev/null
docker exec pg_send_of psql -U send_of -d postgres -c "CREATE DATABASE sccj" >/dev/null
docker exec -i pg_send_of psql -U send_of -d sccj < "$DUMP_SRC"

# Limpa temp
[ -n "$TMP_SQL" ] && rm -f "$TMP_SQL"

echo "✅ Banco restaurado com sucesso: $DUMP_SRC"