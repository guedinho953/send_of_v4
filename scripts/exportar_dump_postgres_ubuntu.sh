#!/usr/bin/env bash
# Exporta o banco real do Docker (pg_send_of) para um arquivo que o Windows
# consegue ler (D:\Projudi\). Rode este script NO UBUNTU, com o container
# pg_send_of ligado.
#
# Uso:
#   bash scripts/exportar_dump_postgres_ubuntu.sh
#   CONTAINER=pg_send_of DB=sccj PGUSER=send_of bash scripts/exportar_dump_postgres_ubuntu.sh
#
# Depois, no Windows:
#   RESTAURAR_BANCO_POSTGRES.bat  (ou scripts\postgres_local_windows.ps1 -DumpFile ...)

set -euo pipefail

CONTAINER="${CONTAINER:-pg_send_of}"
DB="${DB:-sccj}"
PGUSER="${PGUSER:-send_of}"
OUTDIR="${OUTDIR:-/mnt/d/Projudi}"

mkdir -p "$OUTDIR"
ARQUIVO="$OUTDIR/sendof_$(date +%Y%m%d_%H%M%S).sql.gz"

echo "[1/2] Verificando o container $CONTAINER..."
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[ERRO] O container $CONTAINER nao esta rodando."
    echo "       Rode: docker start $CONTAINER"
    exit 1
fi

echo "[2/2] Gerando dump de $DB em $ARQUIVO ..."
docker exec "$CONTAINER" pg_dump \
    -U "$PGUSER" -d "$DB" \
    --no-owner --no-privileges --clean --if-exists \
    | gzip > "$ARQUIVO"

echo "[OK] Dump criado: $ARQUIVO"
echo "     Tamanho: $(du -h "$ARQUIVO" | cut -f1)"
echo ""
echo "No Windows, rode:"
echo "  RESTAURAR_BANCO_POSTGRES.bat"
echo "  (ou .\\scripts\\postgres_local_windows.ps1 -DumpFile \"D:\\Projudi\\$(basename "$ARQUIVO")\")"
