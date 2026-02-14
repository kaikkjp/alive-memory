#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Shopkeeper daily SQLite backup — Docker Compose version
#
# Usage:  bash deploy/docker-backup.sh
#
# Add to crontab:
#   0 4 * * * cd /path/to/shopkeeper && bash deploy/docker-backup.sh >> /var/log/shopkeeper-backup.log 2>&1
# ─────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="./backups"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/shopkeeper-${TIMESTAMP}.db"

# Use SQLite .backup inside the container for a consistent copy
docker compose exec -T shopkeeper python -c "
import sqlite3, shutil, os
db_path = os.environ.get('SHOPKEEPER_DB_PATH', '/app/data/shopkeeper.db')
if os.path.exists(db_path):
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect('/app/data/_backup.db')
    src.backup(dst)
    dst.close()
    src.close()
"

# Copy backup out of container
docker compose cp shopkeeper:/app/data/_backup.db "${BACKUP_FILE}"

# Clean up temp file inside container
docker compose exec -T shopkeeper rm -f /app/data/_backup.db

# Compress
chmod 600 "${BACKUP_FILE}"
gzip "${BACKUP_FILE}"

# Prune old backups
find "${BACKUP_DIR}" -name "shopkeeper-*.db.gz" -mtime +${RETENTION_DAYS} -delete

echo "[backup] Created ${BACKUP_FILE}.gz"
