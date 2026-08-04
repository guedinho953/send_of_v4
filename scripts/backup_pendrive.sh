#!/bin/bash
# Backup para o pendrive E: (Windows) — usa o dump mais recente de backups/
# e copia docs/scripts para /mnt/e/send_of_v4_backup/.
# Uso: ./scripts/backup_pendrive.sh
# Obs.: /mnt/e precisa estar montado com permissão (scripts/montar_pendrive.sh).

set -e

PROJ="$HOME/PythonProjects/send_of_v4"
PEN="/mnt/e/send_of_v4_backup"

if [ ! -d /mnt/e ] || ! touch /mnt/e/.rw_test 2>/dev/null; then
    echo "❌ /mnt/e não está gravável. Monte o pendrive primeiro:"
    echo "   bash $PROJ/scripts/montar_pendrive.sh"
    exit 1
fi
rm -f /mnt/e/.rw_test

mkdir -p "$PEN/banco" "$PEN/docs" "$PEN/scripts"

# Banco: sempre o dump .gz mais recente
ULTIMO=$(ls -t "$PROJ/backups"/sendof_*.sql.gz 2>/dev/null | head -1)
if [ -z "$ULTIMO" ]; then
    echo "⚠️ Sem dump local — gerando agora..."
    bash "$PROJ/scripts/backup_db.sh"
    ULTIMO=$(ls -t "$PROJ/backups"/sendof_*.sql.gz 2>/dev/null | head -1)
fi
cp -f "$ULTIMO" "$PEN/banco/"
echo "✅ Banco: $(basename "$ULTIMO")"

# Scripts
cp -f "$PROJ/scripts/backup_db.sh" "$PROJ/scripts/restaurar_db.sh" "$PEN/scripts/" 2>/dev/null || true
echo "✅ Scripts"

# Docs
cp -f "$PROJ/docs/APRENDIZADOS.md" "$PROJ/docs/modelo-sequencia-cumprimento.json" \
      "$PROJ/docs/referencia-rapida-sequencia.json" \
      "$PROJ/docs/referencia-sequencia-cumprimento-completa.json" "$PEN/docs/" 2>/dev/null || true
echo "✅ Docs"

echo
echo "📦 Backup no pendrive concluído:"
find "$PEN" -type f | sort
du -sh "$PEN"